import csv
import json
import os
import shutil
from datetime import datetime

DATA_DIR = "trading_agent_data"
BOT_IDS = ["momentum", "value", "quant", "growth", "macro"]
INITIAL_CASH_CAD = 1000.0


def backup_existing_data() -> str | None:
    """Sauvegarde les fichiers existants dans un dossier d'archive horodaté."""
    if not os.path.exists(DATA_DIR):
        return None

    files_to_backup = [
        f for f in os.listdir(DATA_DIR)
        if f.endswith((".json", ".csv")) and os.path.isfile(os.path.join(DATA_DIR, f))
    ]
    if not files_to_backup:
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = os.path.join(DATA_DIR, "archives", f"backup_{timestamp}")
    os.makedirs(archive_dir, exist_ok=True)

    for filename in files_to_backup:
        src = os.path.join(DATA_DIR, filename)
        dst = os.path.join(archive_dir, filename)
        shutil.move(src, dst)

    return archive_dir


def reset_all_bots() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    archive_path = backup_existing_data()
    if archive_path:
        print(f"[ARCHIVE] Anciennes données déplacées vers : {archive_path}")
    else:
        print("[ARCHIVE] Aucun fichier existant à archiver.")

    for bot_id in BOTS_TO_RESET:
        portfolio_path = os.path.join(DATA_DIR, f"portfolio_{bot_id}.json")
        trades_path = os.path.join(DATA_DIR, f"trades_{bot_id}.csv")
        logs_path = os.path.join(DATA_DIR, f"logs_{bot_id}.json")

        # 1. Réinitialisation du portefeuille à 1 000 $ CAD
        initial_portfolio = {
            "cash_cad": INITIAL_CASH_CAD,
            "positions": {},
            "history_valuation": [],
            "halted": False
        }
        with open(portfolio_path, "w", encoding="utf-8") as f:
            json.dump(initial_portfolio, f, indent=2, ensure_ascii=False)

        # 2. Réinitialisation du fichier CSV des transactions avec ses en-têtes
        with open(trades_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Date", "Ticker", "Action", "Shares", "Price",
                "FX_Rate", "Fee_CAD", "Cash_CAD_Left", "Reason"
            ])

        # 3. Réinitialisation du journal des réflexions IA
        with open(logs_path, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2, ensure_ascii=False)

        print(f"[OK] Bot '{bot_id}' réinitialisé à {INITIAL_CASH_CAD:.2f} $ CAD.")

    print("\nRéinitialisation terminée : les 5 bots disposent d'un capital neuf de 1 000,00 $ CAD chacun (5 000,00 $ CAD au total).")


BOTS_TO_RESET = BOT_IDS

if __name__ == "__main__":
    reset_all_bots()
