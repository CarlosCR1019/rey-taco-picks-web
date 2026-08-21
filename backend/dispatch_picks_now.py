"""Script manual retirado.

El archivo anterior contenía picks fechados del 18 de agosto y podía volver a
publicarlos por accidente. La única ruta autorizada para publicar una cartera es
``backend.scraper.fase7_guardar_y_notificar``, que aplica la política pública/VIP.
"""


def main():
    raise SystemExit(
        "Dispatch manual retirado: ejecuta backend/scraper.py para generar una cartera vigente."
    )


if __name__ == "__main__":
    main()
