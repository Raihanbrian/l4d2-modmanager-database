# Privacy and local data

The application has no project-operated server, telemetry, account system or login.
It reads the L4D2 root you explicitly choose and the narrowly allowed Workshop
VPK indexes and matched previews. It does not search other Steam libraries or
change game configuration, files, enabled states, subscriptions or load order.

The catalog, original path bytes, inferred targets, corrections, saved folder,
Planning selection, public metadata cache and migration backups are stored only
in `%LOCALAPPDATA%\L4D2ModDatabase`. They remain on your own device/storage, in
the country where that storage is located. Nothing is uploaded to this project.
Deleting or moving the portable application does not delete your local data.
Tests use separate synthetic storage; release ZIPs contain no personal catalog.

Automatic public Steam lookups send validated numeric IDs inferred from your
selected local collection to the fixed HTTPS endpoint:
`https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/`.
Steam receives normal HTTPS connection information, including your network IP.
No Steam credentials, account/subscription list, local path, VPK body or user
correction is sent. Successful public App 550 titles, tags and descriptions are
cached locally with source, timestamps and retrieval status. Official text is
kept separately from user corrections. No remote previews/VPKs are downloaded.

Setup explains the public-ID request. Settings can disable automatic lookups;
an already active bounded request may finish. Success cache is 24 hours, ordinary
error retry is 15 minutes, rate-limit retry one hour. Missing/unavailable items
are not assumed deleted or unsubscribed. Offline failures retain valid caches.
Workshop links open your browser only after you click them; its own policies then
apply. Descriptions display as inert text; embedded links are never followed.

Public Steam information may be unavailable, inaccurate, changed or withdrawn.
It is provided as available, without a warranty of accuracy, uninterrupted access,
fitness or compatibility. Steam data/trademarks remain with Valve and applicable
rights holders. This independent project is not affiliated with or endorsed by
Valve. See [Steam's Web API terms](https://steamcommunity.com/dev/apiterms).

When reporting a bug, review what you share. Remove personal paths, account data,
database contents and unrelated screenshots. The app does not submit bug reports
automatically. Public release remains subject to the owner's final terms/license
review; this document is a factual description of current behavior.
