from flask import Flask, render_template_string, jsonify
import requests
import pandas as pd
import time
import ast
import threading
import datetime
import os
from http.client import IncompleteRead

app = Flask(__name__)

# ==========================================
# CONFIGURAÇÕES E URLS
# ==========================================
URL_DASHBOARD = "https://abmbus.com.br:8181/api/dashboard/mongo/95?naoVerificadas=false&agrupamentos="
URL_TROCA = "https://abmbus.com.br:8181/api/linha/trocarveiculos"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Authorization": "eyJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJtaW1vQGFibXByb3RlZ2UuY29tLmJyIiwiZXhwIjoxODYwNzEwOTEyfQ.2yLysK8kK1jwmSCYJODCvWgppg8WtjuLxCwxyLnm2S0qAzSp12bFVmhwhVe8pDSWWCqYBCXuj0o2wQLNtHFpRw",
    "Content-Type": "application/json"
}

SHEET_XLSX_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSH9lJhzNgDz3x05wnE3lc24YKiUQcn_WTNgxEpsSO2jA36rAwSDfLZUkm1SgE_uoKBXvgx1_8sDTXZ/pub?output=xlsx"
LINHAS_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQ-jeDXdqfWvVcRQL-aPgyeLstQxwRU0gQnVfzEDfU476vmHcPTaFKqJkdf6NjFEeyRW_TGotfGbodG/pub?gid=0&single=true&output=csv"
CARROS_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTlOLnEeXNsgsK2uK0-hHwVhiaE6lsYUMdUE4cxJ5cVSq1YnuEtbJekwd1MS-lP1Gvybn8CYSuyuXIm/pub?gid=0&single=true&output=csv"

# Variável global para armazenar logs do que o robô fez
logs_robo = []

# ==========================================
# FUNÇÕES AUXILIARES (LÓGICA)
# ==========================================

def carregar_planilhas():
    nome_aba = time.strftime("%d%m%Y")
    for tentativa in range(3):
        try:
            print(f"🔄 Tentando carregar planilhas (Tentativa {tentativa+1})...")
            df_sheet = pd.read_excel(SHEET_XLSX_URL, sheet_name=nome_aba)
            df_linhas = pd.read_csv(LINHAS_CSV_URL)
            df_carros = pd.read_csv(CARROS_CSV_URL)
            return df_sheet, df_linhas, df_carros
        except Exception as e:
            print(f"⚠️ Erro ao ler planilhas: {e}")
            time.sleep(3)
    return None, None, None

def obter_veiculo_escala(codLinha, df_sheet, df_linhas):
    try:
        codLinha = str(codLinha).strip()
        for _, linha_sheet in df_sheet.iterrows():
            valor_coluna_D = str(linha_sheet.iloc[3]).strip()
            linha_linhas = df_linhas[df_linhas.iloc[:, 0].astype(str).str.strip() == valor_coluna_D]
            if not linha_linhas.empty:
                valor_coluna_B = str(linha_linhas.iloc[0, 1]).strip()
                if valor_coluna_B == codLinha:
                    valor_coluna_G = linha_sheet.iloc[6] if not pd.isna(linha_sheet.iloc[6]) else linha_sheet.iloc[5]
                    if isinstance(valor_coluna_G, float) and valor_coluna_G.is_integer():
                        valor_coluna_G = int(valor_coluna_G)
                    return str(valor_coluna_G).strip()
        return "ZZZ-8888"
    except:
        return "ZZZ-8888"

def obter_dados_carro(veiculo_escala, df_carros):
    # Retorna (codigo_veiculo, coluna_c_carro)
    try:
        veiculo_escala = str(veiculo_escala).strip()
        linha_carro = df_carros[df_carros.iloc[:, 0].astype(str).str.strip() == veiculo_escala]
        if linha_carro.empty:
            return "ZZZ-8888", "ZZZ-8888"
        return str(linha_carro.iloc[0, 1]).strip(), str(linha_carro.iloc[0, 2]).strip()
    except:
        return "ZZZ-8888", "ZZZ-8888"

def executar_troca_api(id_veiculo, id_linha, id_relatorio):
    try:
        hoje = datetime.datetime.now().strftime("%d/%m/%Y")
        
        # Garante que id_linha seja uma lista
        if isinstance(id_linha, (int, str)) and not isinstance(id_linha, list):
            id_linha = [id_linha]

        payload = {
            "idVeiculo": id_veiculo,
            "linhas": id_linha,
            "dataInicial": hoje,
            "dataFinal": hoje
        }

        print(f"🚀 Enviando troca: Veículo {id_veiculo} nas linhas {id_linha}")
        response = requests.post(URL_TROCA, headers=HEADERS, json=payload)
        response.raise_for_status()
        
        # Marca relatório como alterado (opcional, baseado no seu JS original)
        if id_relatorio:
            url_rel = f"https://abmbus.com.br:8181/api/linha/marca_relatorio_alterado?id={id_relatorio}&alterado=true"
            requests.post(url_rel, headers=HEADERS)
            
        return True, response.text
    except Exception as e:
        return False, str(e)

# ==========================================
# ROBÔ DE FUNDO (BACKGROUND TASK)
# ==========================================
def tarefa_monitoramento():
    """Esta função roda em loop infinito numa thread separada"""
    print("🤖 Robô de monitoramento iniciado.")
    
    while True:
        print("\n🔎 Robô: Verificando status da frota...")
        try:
            # 1. Carrega dados
            df_sheet, df_linhas, df_carros = carregar_planilhas()
            if df_sheet is None:
                print("❌ Robô: Falha ao carregar planilhas. Tentando em 1 min.")
                time.sleep(60)
                continue

            # 2. Busca API da Dashboard
            resp = requests.get(URL_DASHBOARD, headers=HEADERS)
            dados_api = resp.json()
            
            # 3. Processa linhas
            listas_verificar = dados_api.get("linhasAndamento", []) + \
                               dados_api.get("linhasCarroDesligado", []) + \
                               dados_api.get("linhasComecaramSemPrimeiroPonto", [])

            for l in listas_verificar:
                codLinha = l.get("codLinha")
                veiculo_atual_api = l.get("veiculo", {}).get("veiculo", "ZZZ-8888").strip()
                id_linha_api = l.get("idLinha")
                id_relatorio = l.get("idRelatorio")
                
                # Descobre qual deveria ser o veículo correto
                veiculo_escala = obter_veiculo_escala(codLinha, df_sheet, df_linhas)
                codigo_veiculo_novo, placa_correta = obter_dados_carro(veiculo_escala, df_carros)

                # LÓGICA DE COMPARAÇÃO
                # veiculo_atual_api: O que está rodando agora (ex: ABC-1234)
                # placa_correta: O que deveria estar rodando (coluna C da planilha carros)
                
                if placa_correta != "ZZZ-8888" and veiculo_atual_api != placa_correta:
                    print(f"⚠️ Divergência! Linha {codLinha}: Atual [{veiculo_atual_api}] vs Correto [{placa_correta}]")
                    
                    # Executa a troca
                    sucesso, msg = executar_troca_api(codigo_veiculo_novo, id_linha_api, id_relatorio)
                    
                    log_msg = f"{datetime.datetime.now().strftime('%H:%M')} - Linha {codLinha}: Troca de {veiculo_atual_api} para {placa_correta} ({'Sucesso' if sucesso else 'Erro'})"
                    logs_robo.insert(0, log_msg) # Adiciona no topo da lista
                    
                    if len(logs_robo) > 50: logs_robo.pop() # Mantém apenas últimos 50 logs
                
        except Exception as e:
            print(f"❌ Erro no ciclo do robô: {e}")
        
        print("💤 Robô dormindo por 3 minutos...")
        time.sleep(180) # Espera 3 minutos (180 segundos)

# ==========================================
# ROTAS FLASK (Apenas visualização)
# ==========================================
@app.route('/')
def index():
    # A página agora serve apenas para você ver o que o robô está fazendo
    # Não tem mais lógica de troca no Javascript aqui
    
    logs_html = "<br>".join(logs_robo) if logs_robo else "Nenhuma ação registrada ainda."
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Monitoramento Automático ABM</title>
        <meta http-equiv="refresh" content="60"> <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="p-4">
        <h2>🤖 Status do Robô Automático</h2>
        <div class="alert alert-info">
            O sistema está rodando no servidor. Não é necessário manter esta janela aberta para efetuar as trocas.
        </div>
        
        <div class="card">
            <div class="card-header bg-dark text-white">Log de Operações (Últimas ações)</div>
            <div class="card-body">
                {logs_html}
            </div>
        </div>
        
        <br>
        <p class="text-muted small">Status atualizado em: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
    </body>
    </html>
    """
    return html

# ==========================================
# INICIALIZAÇÃO
# ==========================================
if __name__ == "__main__":
    # Inicia a thread do robô
    t = threading.Thread(target=tarefa_monitoramento)
    t.daemon = True 
    t.start()
    
    # PEGA A PORTA DO RENDER OU USA 5000 SE FOR LOCAL
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
