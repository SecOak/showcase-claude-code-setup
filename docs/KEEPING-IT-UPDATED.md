# Keeping it updated

Your copy of this repository has two remotes (places Git can fetch from):

| Name | What it points to | What you do with it |
|------|-------------------|---------------------|
| `origin` | Your own private repository | Push your changes here. |
| `upstream` | This shared repository | Fetch improvements from here. You can read it but not push to it. |

If you followed [MOVE-TO-YOUR-OWN-GITHUB.md](MOVE-TO-YOUR-OWN-GITHUB.md), both are set up
already. Check with:

```powershell
git -C "$env:USERPROFILE\repos\shared-tooling" remote -v
```

## Add the upstream remote (once)

Only if `upstream` is missing. In PowerShell, replacing `<SHARED_REPOSITORY_URL>` with the
address of this shared repository:

```powershell
git -C "$env:USERPROFILE\repos\shared-tooling" remote add upstream <SHARED_REPOSITORY_URL>
```

## Pull in updates

All commands run in PowerShell inside your copy:

```powershell
Set-Location "$env:USERPROFILE\repos\shared-tooling"
```

1. **Save your own work first.** Commit anything you changed:

   ```powershell
   git status
   git add -A
   git commit -m "My changes before updating"
   ```

2. **Fetch what is new:**

   ```powershell
   git fetch upstream
   ```

3. **See what changed before you take it:**

   ```powershell
   git log --oneline main..upstream/main
   git diff main upstream/main --stat
   ```

4. **Merge it into your copy:**

   ```powershell
   git merge upstream/main
   ```

   If Git opens an editor for the merge message, save and close it.

5. **Push the result to your own repository:**

   ```powershell
   git push origin main
   ```

6. **Apply the new versions on this computer:**

   ```powershell
   .\deploy\Deploy-Hooks.ps1 -Apply
   ```

   If `config\` changed and you want the new settings, run
   `.\scripts\Restore-ClaudeSeat.ps1 -SkipInstalls`. It saves your current files as
   `*.pre-restore-*` before replacing them.

## When the merge reports a conflict

A conflict means you and the shared repository changed the same lines. Git stops and
lists the files.

1. See which files conflict:

   ```powershell
   git status
   ```

2. Open each file listed under "both modified". Git marks the clash like this:

   ```text
   <<<<<<< HEAD
   your version
   =======
   the shared version
   >>>>>>> upstream/main
   ```

3. Edit the file so it holds what you want: yours, theirs, or a mix. Delete the three
   marker lines.

4. Mark it resolved and finish:

   ```powershell
   git add <FILE>
   git commit
   ```

Shortcuts for a whole file:

```powershell
git checkout --ours   <FILE>   # keep your version
git checkout --theirs <FILE>   # take the shared version
git add <FILE>
```

To give up and go back to how things were before the merge:

```powershell
git merge --abort
```

## Files you are expected to change

You will almost certainly change `config\CLAUDE.md`, `config\settings.json` and
`config\seat-local\`, and `Sync-ClaudeSeat.ps1` overwrites them from your live
configuration. Conflicts in those files are normal: keep yours (`--ours`) unless the
shared change is something you want, then copy that part in by hand.

The scripts, hooks and documents are the parts most likely to improve upstream. Where you
have not changed them, the merge takes the new version without asking.
