# ================================================
# File: server/routes/__init__.py
# ================================================
# This file imports all the individual route modules.
# When the `routes` package is imported by `server/__init__.py`,
# these imports will be executed, registering the routes with the
# ComfyUI server instance.

from . import CancelDownload
from . import ClearHistory
from . import DownloadModel
from . import GetBaseModels
from . import GetModelDetails
from . import GetModelTypes
from . import GetModelDirs
from . import GetStatus
from . import OpenPath
from . import RetryDownload
from . import SearchModels

print("[Civicomfy] All server route modules loaded.")
