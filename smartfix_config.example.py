from pathlib import Path

# Exchange Basisordner (ohne Mandant - wird dynamisch angehängt)
EXCHANGE_BASE = r"\\SVM07561\current\Exchange"

# SOAP Zugangsdaten
USERNAME = "smartFIX"
PASSWORD = "insiders"

# SOAP Service
SOAP_ADDRESS = "http://svm07561.ruv.de:8050"
SOAP_ENDPOINT = "/smartFIXServices"

# WSDL-Datei im aktuellen Projektordner
WSDL_PATH = str(Path(__file__).resolve().parent / "sf.wsdl")

# Import-Konfiguration
PRIORITY = "5"
EXPORT_VERIFIER_DOCUMENTS = "TRUE"
EXPORT_SUPERVISOR_DOCUMENTS = "TRUE"
