# Central HAIZEN

Faturamento, clientes, tarefas, pipeline e agentes numa página web que roda no seu PC, sem internet e sem mensalidade. Substitui o sistema do Base44.

| Tela | O que faz |
| --- | --- |
| Painel | Lucro do período, recebido x custos dos últimos 12 meses, a receber, a pagar, tarefas atrasadas, quem mais pagou, pipeline |
| Financeiro | Receitas e despesas; um clique na situação marca como recebido/pago |
| Clientes | Ficha de cada cliente pagador: total recebido, em aberto, tarefas, marcas e pastas do Drive |
| Tarefas | Quadro A Fazer, Em Andamento, Em Revisão e Concluída; arraste para mudar |
| Pipeline | Lead, Contato, Proposta, Negociação, Ganho e Perdido, com valores |
| Agentes | Pedir trabalhos aos agentes da HAIZEN e aprovar as entregas |

## Abrir

```powershell
py -m haizen.central
```

Ou diga ao Jarvis: "abre a central". O endereço é `http://127.0.0.1:8765`. Pelo celular não funciona, de propósito: a central só aceita conexões do próprio PC.

## Trazer os dados do Base44 (uma vez)

1. No Base44, exporte Cliente, Receita, Despesa, Tarefa, Subtarefa e Oportunidade em CSV.
2. Ponha os arquivos em `C:\JARVIS\importar_base44\` (essa pasta nunca vai para o GitHub).
3. Rode:

```powershell
py -m haizen.importar_base44 importar_base44 --drive "G:\Meu Drive\CLIENTES" --apagar-csv
```

O `--apagar-csv` apaga os CSVs depois, porque eles têm senhas em texto puro. Pode rodar de novo sem duplicar nada: cada registro é reconhecido pelo id do Base44.

## Clientes e marcas

- **Cliente** é quem paga (uma agência parceira, uma empresa, uma universidade...). É nele que fica o faturamento.
- **Marca** é cada pasta do Drive, como cada empresa atendida por meio de uma agência parceira. O importador liga cada marca ao cliente que paga por ela, pelo nome ou pelas tarefas e receitas que a citam. Na ficha do cliente, clicar numa marca abre a pasta no Explorer e permite corrigir a ligação.

## Logins e senhas

Logins e senhas que estavam no texto das tarefas foram para um campo **Acessos**, que só aparece quando você clica em "Mostrar acessos". Eles ficam fora das listagens, fora do Claude e fora dos agentes de IA.

Como essas senhas ficaram anos em texto puro no Base44, vale trocar as mais importantes e passar a guardá-las num gerenciador de senhas (Bitwarden, por exemplo).

## Pelo Claude

Com o servidor MCP da HAIZEN ligado, o Claude também vê a central:

- "Quanto a HAIZEN faturou em setembro?"
- "Liste as tarefas abertas da Agência Norte."
- "Registre uma receita de R$ 1.200 da Padaria Sol, vencimento dia 10."

## Onde ficam os dados

No mesmo banco da HAIZEN: `%LOCALAPPDATA%\JarvisGPT\haizen.db`. Para fazer backup, copie esse arquivo com o Jarvis e a central fechados.
