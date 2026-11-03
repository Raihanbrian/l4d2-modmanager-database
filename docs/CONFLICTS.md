# What the warnings mean

The application confirms shared canonical resource paths in indexed VPKs. It does
not compare their full contents, run the game or decide which addon wins.

| Reason | Interpretation |
|---|---|
| Same supported original model resource | Potential replacement competition; one version may take priority |
| Shared material/texture, sound or UI/localization | Resource competition can affect different apparent original targets |
| Shared script/config | Behavior may change; execution/dependencies require investigation |
| Other model/dependency or unknown resource | Indexed overlap is known; payload compatibility is not evaluated |
| Root addon metadata only | Informational, not a dangerous failure |
| Stale/incomplete indexes | Retained evidence or unknown coverage; refresh before drawing conclusions |

Planning highlights affected mod rows in pale red only for current resource
overlaps where both packages are selected. Unaffected, metadata-only and retained
stale rows keep normal colors; stale evidence remains labeled for refresh.
A package outside your set cannot create a selected-pair warning. Advanced metadata rows and optional
byte-safe technical paths retain the underlying evidence. A session review mark
does not remove a finding, clear its red highlight or declare it harmless. It clears after relevant changes
or restart. One Planning set is saved; the game enabled list is not changed.

**Crash evidence defaults to Not verified.** A reported visual issue, rejected
join, consistency kick and application crash are distinct observations. No overlap
does not prove full compatibility; semantic scripts, missing dependencies, model
internals, animation behavior and engine resource limits are not evaluated. There
is no arbitrary risk percentage, crash predictor or multiplayer-safe certificate.

Valve's [2010 update](https://store.steampowered.com/oldnews/4235) introduced a
command for observing addon load order. It does not specify today's complete
internal conflict algorithm. We infer possible priority competition, not an exact
winning package. Mod-author explanations such as ChimiChamo's
[guide](https://steamcommunity.com/sharedfiles/filedetails/?id=3262352793) discuss
model/material overlap; ZeqMacaw's [survivor naming tutorial](https://sites.google.com/view/zeqmacawstidbits/tutorials/modding-a-left-4-dead-2-survivor/modding-related-visual-elements/modding-the-name)
explains that multiple survivor names share a localization file. These are useful
mechanism examples, not tests of your collection. Community/runtime claims require
their own evidence and are not automatically promoted to verified crash causes.
