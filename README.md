# Painel de Gestao

Painel para cadastro de analises de monitoracao e leitura de planilhas Google com dashboard consolidado para `Sinalizacao Vertical`.

## O que esta pronto

- Cadastro de analises com `Link Principal` e ate `2` links adicionais
- Leitura automatica e validacao individual de cada fonte
- Identificacao inicial de `Monitoracao de Sinalizacao Vertical`
- Identificacao da fonte principal e da aba `Medicao`
- Dashboard com resumo, status, tipos de placas, dimensoes registradas e observacoes
- Drilldown por `FICHA`, agrupado por `UF`
- Secao `Dimensoes Registradas` agrupada por `CodigoOuTipo`, com combinacoes de `Largura x Altura` e contagem
- Execucao local pelo servidor Python atual
- Execucao e deploy pelo Streamlit usando `streamlit_app.py`

## Estrutura principal

- `server.py`: servidor HTTP local e regras de leitura/agrupamento do dashboard
- `streamlit_app.py`: interface pronta para rodar localmente com Streamlit e publicar no Streamlit Community Cloud
- `static/`: frontend da versao HTTP local
- `requirements.txt`: dependencias para o modo Streamlit

## Como executar localmente

### Opcao 1: servidor HTTP atual

1. No terminal, entre na pasta do projeto.
2. Execute:

```bat
python server.py
```

3. O servidor vai mostrar os enderecos disponiveis, por exemplo:

```text
http://127.0.0.1:4173
http://192.168.137.1:4173
```

4. Abra um dos enderecos no navegador.

Tambem e possivel iniciar com duplo clique em `start.bat`.

### Opcao 2: Streamlit

1. No terminal, entre na pasta do projeto.
2. Instale as dependencias:

```bat
pip install -r requirements.txt
```

3. Rode o app:

```bat
streamlit run streamlit_app.py
```

4. O Streamlit abrira automaticamente no navegador ou mostrara a URL local no terminal.

## Configuracoes opcionais do servidor HTTP

- `PAINEL_HOST`: define o host de bind do servidor (padrao: `0.0.0.0`)
- `PAINEL_PORT`: define a porta (padrao: `4173`)

Exemplo no Windows:

```bat
set PAINEL_HOST=0.0.0.0
set PAINEL_PORT=4173
python server.py
```

## Publicar no GitHub

Passo a passo para criar o repositorio e enviar o projeto:

1. Abra um terminal na pasta do projeto.
2. Inicialize o Git, se ainda nao existir repositorio:

```bat
git init
```

3. Adicione os arquivos:

```bat
git add .
```

4. Crie o primeiro commit:

```bat
git commit -m "Primeira versao do Painel de Gestao"
```

5. No GitHub, crie um repositorio novo.
6. Copie a URL do repositorio criado, por exemplo:

```text
https://github.com/SEU_USUARIO/painel-gestao.git
```

7. Conecte o repositorio local ao remoto:

```bat
git remote add origin https://github.com/SEU_USUARIO/painel-gestao.git
```

8. Defina a branch principal como `main`:

```bat
git branch -M main
```

9. Envie o codigo:

```bat
git push -u origin main
```

10. Nas proximas alteracoes, o fluxo normal sera:

```bat
git add .
git commit -m "Descricao da alteracao"
git push
```

### Se o repositorio no GitHub ja existir

Se voce ja tiver criado o repositorio no GitHub antes do `git init`, basta usar:

```bat
git add .
git commit -m "Descricao da alteracao"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/painel-gestao.git
git push -u origin main
```

## Publicar no Streamlit Community Cloud

Fluxo conferido nas docs oficiais do Streamlit em `18/03/2026`:

- Deploy: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- Dependencias: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies

Passo a passo:

1. Garanta que o projeto ja esteja publicado no GitHub.
2. Acesse o Streamlit Community Cloud:

```text
https://share.streamlit.io/
```

3. Entre com sua conta e conecte o GitHub, se solicitado.
4. Clique em `Create app`.
5. Selecione o repositorio do projeto.
6. Escolha a branch que sera publicada, normalmente `main`.
7. Em `Main file path`, informe:

```text
streamlit_app.py
```

8. Se quiser, ajuste o nome da URL publica do app.
9. Clique em `Deploy`.

### Importante para o deploy

- O arquivo `requirements.txt` ja esta no projeto para o Streamlit instalar as dependencias.
- O app Streamlit usa a mesma logica de leitura de planilhas do `server.py`.
- No Streamlit Community Cloud, as analises cadastradas ficam na sessao atual do navegador. Para persistencia definitiva entre acessos, sera necessario adicionar armazenamento externo.
- Sempre que voce fizer `git push` na branch publicada, o app podera ser atualizado pelo Streamlit.

## Observacoes

- O backend local em Python faz a leitura da planilha Google para evitar problemas de CORS no navegador.
- A classificacao esta preparada para crescer com novos tipos de banco, mas por enquanto reconhece apenas o fluxo de `Sinalizacao Vertical`.
- Para `Sinalizacao Vertical`, a analise exige uma fonte principal e uma fonte adicional do tipo `Medicao`.
