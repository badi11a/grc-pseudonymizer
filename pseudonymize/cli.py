import argparse
import os
import sys

from .pipeline import run


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="grc-pseudonymizer",
        description="Framework de seudonimización batch para bases de datos relacionales con interfaz web y trazabilidad normativa",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  pseudonymize --config config.yaml\n"
            "  pseudonymize --config config.yaml --db-url postgresql://user:pass@host/db\n"
        ),
    )
    parser.add_argument(
        "--config",
        required=True,
        metavar="FILE",
        help="Ruta al fichero de configuración YAML",
    )
    parser.add_argument(
        "--db-url",
        metavar="URL",
        help="URL de conexión SQLAlchemy (sobreescribe db_url del config)",
    )
    args = parser.parse_args()

    db_url = args.db_url or os.environ.get("DB_URL")

    try:
        run(args.config, db_url)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error de configuración: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"Error inesperado: {e}", file=sys.stderr)
        sys.exit(3)
