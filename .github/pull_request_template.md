<!-- dsi-toolbox pull request template. The canonical copy is kit/dsi-toolbox/templates/pull_request_template.md in Pathforward, and scripts/sync_toolbox.py replaces this file from it. Change it there. Delete this line and the file becomes this repository's own, which the sync leaves alone. -->

## What changed, and what it is measured against

<!-- One paragraph. The diff says what moved. This says why, and against what: the issue, the spec clause, the defect, or the behavior before the change. -->

## Which gate passed

<!-- Name each check by the command or tool that ran it. This repository's CLAUDE.md lists them. Give passed, failed and skipped as three counts. "The suite passes", "the vendor tool imported it" and "I read the code" are different claims. Name every check you did not run, and why. -->

## What was falsified

<!-- When this adds or changes a check: put the defect back, watch the check fail, and name what you injected and which test fired. An injection that did not apply reads exactly like a dead check. Write "No check changed" when none did. -->

## What this does not claim

<!-- What was not measured, what only a controller, a vendor tool or a person can settle, and any blind spot the change leaves. -->

## What is left for the reviewer

<!-- Numbered steps that are now the reviewer's: a merge, a step on a machine, a decision. "Nothing" is an answer. -->
