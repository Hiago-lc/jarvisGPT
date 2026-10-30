"""py -m haizen.central — abre a central no navegador e fica rodando."""
import sys
import time
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from haizen.central import servidor  # noqa: E402

if __name__ == "__main__":
    abrir = "--sem-navegador" not in sys.argv
    print(f"Central HAIZEN em {servidor.iniciar(abrir)}  (Ctrl+C para fechar)")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        servidor.parar()
