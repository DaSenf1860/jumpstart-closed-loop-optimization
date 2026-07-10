from pathlib import Path

from azure.identity import AzureCliCredential
from fabric_cicd import FabricWorkspace, publish_all_items

# Standalone deploy (without fabric-jumpstart). Set your target workspace id.
# parameter.yml uses `_ALL_` replacements, so no `environment` is required.
WORKSPACE_ID = "00000000-0000-0000-0000-000000000000"

repo_dir = Path(__file__).resolve().parent
workspace = FabricWorkspace(
    workspace_id=WORKSPACE_ID,
    repository_directory=str(repo_dir),
    item_type_in_scope=["Eventhouse", "KQLDatabase", "Notebook", "KQLDashboard", "Reflex"],
    token_credential=AzureCliCredential(),
)

publish_all_items(workspace)
