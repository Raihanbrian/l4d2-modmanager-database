L4D2 Workshop Collection Manager — M6.4 / 0.1.0rc4 — Windows x64 pre-release

Extract the entire ZIP to a local folder. Open L4D2ModDatabase.exe.
Windows 10/11 x64; no Python installation or administrator privileges required.
Keep the _internal folder next to the EXE.

Select your Left 4 Dead 2 game root once (the folder containing left4dead2).
The app reads local Workshop VPK indexes and matched JPG previews. It never
changes game files, enabled states, subscriptions, load order or server settings.
Refresh Mods after Steam/game Workshop synchronization finishes; subscriptions
do not always produce local files immediately. Missing files do not prove an
unsubscription. Your saved catalog and edits remain in:
%LOCALAPPDATA%\L4D2ModDatabase

Cached information opens offline. Public Steam titles/tags/descriptions refresh
in the background (24-hour success cache; 15-minute error / 1-hour rate retry).
Settings can disable automatic requests or retry due items. Only locally inferred
numeric Workshop IDs are sent to the fixed Steam API. No Steam account login.
Workshop links open only when clicked.

All Mods: use one Category / Target chooser; Status shows Confirmed, Suggested,
Needs Review or Stale. Suggested values are unconfirmed. Open Mod Details to
correct target/replacement/description and Save Changes. Advanced editing and
technical evidence are optional. Changes preserve unsaved drafts until saved
or explicitly discarded. More options holds Custom catalog name, which is
separate from Replacement / Change and the official Steam title.
Unreadable files with no indexed change disable replacement editing until
recovery; notes and optional catalog names can still be saved.

Planning: check mods to keep one persistent selection. Read Mod / Conflicts with /
Reason for selected pairs. Expand technical paths if needed. Common package
metadata is informational. Exact path competition does not prove a crash, and
no overlap does not prove compatibility. Runtime crash evidence is Not verified.
The app does not test campaign/multiplayer behavior or detect all dependency,
animation, script or engine-limit failures. Review stale/incomplete coverage.

Known limits: conservative target dictionary; unknown/mixed replacements need
review; description inference deferred; large/corrupt previews use placeholders;
no verified engine path-comparison semantics; limited live VPK v2 coverage;
native symlink/junction tests skipped where Windows privileges are unavailable.

This EXE is unsigned. Windows may show trust/reputation warnings. Verify its
source and SHA256; do not disable system security globally. Code signing and
a broad runtime gameplay certification have not been performed.
See LICENSE (MIT), PRIVACY.txt, LICENSE_REVIEW.txt and THIRD_PARTY_NOTICES.txt.
The original Python Windows binary conditions and all dependency notices are retained
in the licenses folder. Project MIT terms do not relicense third-party components.
