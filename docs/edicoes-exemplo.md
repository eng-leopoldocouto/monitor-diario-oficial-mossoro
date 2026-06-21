# Edições do DOM para teste e desenvolvimento

Edições reais do Diário Oficial de Mossoró com características conhecidas, úteis
para validar manualmente os diferentes caminhos do código sem depender da edição
mais recente.

## Como usar

Reprocessa a edição escolhida e envia ao **grupo de testes** (não altera o
controle real `ULTIMO_DOM_NUMERO`):

```bash
python monitor_diario_oficial.py --test <NÚMERO>
```

Ex.: `python monitor_diario_oficial.py --test 835`

## Edições de referência

| DOM Nº | Ocorrências | PDFs | Fofocas | Ponto facult. | Bom para testar |
|-------:|-------------|:----:|:-------:|:-------------:|-----------------|
| **845** | 3 (Gestor, Fiscal, Gestor Substituto) | 1 | 0 | — | Extração de função (gestor/fiscal/substituto) e **agrupamento** de várias ocorrências num só PDF |
| **835** | 5 (Gestor ×4, Gestor Substituto) | 5 | 0 | — | Envio de **múltiplos PDFs** (caminho de vários anexos) |
| **841** | 1 (Participação) | 1 | 0 | — | Extração via **participação** (quando não é gestor/fiscal de contrato) |
| **838** | 1 | 1 | 0 | — | Caso simples: uma ocorrência, um PDF |
| **833** | 0 | 0 | 1 | 1 | **Fofoca** + **ponto facultativo** (sem ocorrências) |
| **844** | 0 | 0 | 3 | — | Detecção de **múltiplas fofocas** (movimentações de secretaria) |
| **839** | 0 | 0 | 0 | — | Edição **vazia**: aviso "nenhuma ocorrência" + bloco de fofoca vazio |

## Caminhos cobertos

- **Ocorrências + PDF** (mensagem principal + anexos): 845, 835, 841, 838
- **Vários anexos numa só operação**: 835
- **Agrupamento de ocorrências no mesmo PDF**: 845
- **Sem ocorrências → aviso ao grupo**: 833, 844, 839
- **Seção de fofoca preenchida**: 833 (1), 844 (3)
- **Ponto facultativo**: 833

> Nota: as características acima refletem o conteúdo dessas edições no momento do
> registro. Se o conteúdo de uma edição for corrigido/republicado no site, os
> números podem divergir — revalide ao usar como referência.
