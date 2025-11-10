# cursor-test

## Script H&M - Verificação de Disponibilidade de Tamanhos

### Instalação

1. Instale as dependências:
```bash
pip install -r requirements.txt
playwright install chromium
```

### Uso

Execute o script:
```bash
python hm_br_sizes_to_excel.py
```

O script irá:
- Abrir a página de categoria da H&M
- Descobrir URLs de produtos (PDPs)
- Para cada produto, verificar a disponibilidade dos tamanhos:
  - **Esgotado**: Botão desabilitado ou com risco/texto riscado
  - **Poucas unidades**: Botão funcional mas com quadrado vermelho indicador
  - **Disponível**: Sem indicadores visuais
- Gerar arquivo Excel `hm_status.xlsx` com os resultados

### Configuração

Edite as variáveis no início do arquivo `hm_br_sizes_to_excel.py`:
- `PRODUCT_LIMIT`: Número máximo de produtos a processar (padrão: 5)
- `HEADLESS`: `True` para executar sem interface gráfica, `False` para ver o navegador
- `CATEGORY_URL`: URL da categoria a ser analisada