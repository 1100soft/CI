# 1100soft shared CI

Reusable GitHub Actions workflows for Mountlet, Cerberus, and future Tauri desktop
applications. Callers retain triggers, path filters, concurrency, release gates,
and app-specific commands. Shared jobs check out **the caller's repository**.

| Workflow | Responsibility | Required inputs |
| --- | --- | --- |
| `tauri-check.yml` | npm frontend build, native compilation, Linux tests, optional Clippy and app checks | `app-directory` |
| `tauri-package.yml` | Native toolchains, platform dependencies, matrix builds, bundle verification, artifact uploads | `app-directory`, `artifact-prefix`, `build-matrix` |
| `node-check.yml` | Lockfile-based npm install and caller checks | `check-command` |
| `apt-publish.yml` | Download tested artifacts, run caller Debian validation/preparation, upload and dispatch to APT service | `artifact-inputs`, `prepare-command`; `APT_DISPATCH_TOKEN` secret |
| `validate.yml` | Lint shared workflows and test build/download contracts | Runs on pushes and pull requests |

Node 22 and Rust stable are defaults. All build jobs have read-only contents
permissions, bounded runtimes, and matrices that continue other platforms after
one fails. APT additionally requires `actions: read`. No shared workflow creates
or promotes releases. App packaging is independent of website tests.

## Using the workflows

```yaml
jobs:
  desktop:
    uses: 1100soft/CI/.github/workflows/tauri-check.yml@<full-commit-SHA>
    with:
      app-directory: desktop
      check-command: node scripts/check-release-version.mjs
      linux-check-command: bash scripts/check-webkit-ci.sh
  package:
    uses: 1100soft/CI/.github/workflows/tauri-package.yml@<full-commit-SHA>
    with:
      app-directory: desktop
      artifact-prefix: my-app
      version-check-command: node scripts/check-release-version.mjs
      build-matrix: |
        {"include":[
          {"os":"ubuntu-24.04","target":"x86_64-unknown-linux-gnu","bundles":"deb,appimage"},
          {"os":"windows-2022","target":"x86_64-pc-windows-msvc","bundles":"nsis"},
          {"os":"macos-15","target":"aarch64-apple-darwin","bundles":"app,dmg"},
          {"os":"macos-15-intel","target":"x86_64-apple-darwin","bundles":"app,dmg"}
        ]}
```

Pin callers to a reviewed full commit SHA. Runner choices and target coverage are
caller policy: Cerberus also builds Linux ARM64; Mountlet builds eight native
platform/variant combinations. Both currently use npm lockfiles and the standard
`src-tauri` layout beneath their app directory. Mobile builds and production
publisher signing are outside this contract.

## Desktop checks

`runner-matrix` is a JSON array of runner labels; the default covers Ubuntu x64,
Windows x64, and Apple Silicon macOS. Every runner performs `npm ci`,
`npm run build`, caller `check-command`, and native test compilation. Linux runs
`native-test-command` (serial native tests by default) and `linux-check-command`.
`clippy` defaults to false; `post-native-command` can probe a built executable.
Commands execute in `app-directory` using Bash with strict error handling.
Branch exclusions, including Cerberus's autosave policy, belong to callers.

## Packages and app hooks

Matrix entries normally contain `os`, `target`, and comma-separated `bundles`.
Supported bundles are `deb`, `appimage`, `nsis`, `dmg`, and `app`; app bundles are
validated in `bundle/macos` and distributed inside DMGs. Every requested bundle
must exist before upload. `variant` adds an artifact suffix and cache identity.
Use `prepare-command` / `verify-command` for small app tasks; they receive
`BUILD_TARGET` and `BUILD_VARIANT`. `check-command` runs before the installer build.
The default build command passes the explicit target, bundle list, and Cargo
`--locked` to the npm `tauri` script.

For applications with a custom build driver, `build-command` can replace that
command. `target` and `bundles` may then be omitted; the app hook must validate
its outputs. Set matrix `artifact` and repository-relative `artifact-path` to
retain stable installer names and existing download contracts. Artifact names
must be unique across the matrix. `retention-days` defaults to 30.

Set `app-hooks: true` for structured app-owned composite actions at:

- `.github/actions/tauri-prepare/action.yml`, after npm install and command preparation.
- `.github/actions/tauri-verify/action.yml`, after build and command verification, before installer upload.

Each action receives a `matrix` input containing the complete entry as JSON.
Composite actions use `fromJSON(inputs.matrix)` in place of workflow `matrix`.
They own their working directories and shell choices; package workflow defaults
do not propagate into composite actions. These actions live in the **caller**,
so no second checkout or shared-repository token is needed.

Mountlet uses these hooks for rclone staging, variant checks, stable installer
names, Linux/Windows/macOS installed-app probes, MSIX creation and certification,
and the separate Store submission artifact. Its OAuth build credentials are
explicitly forwarded as a JSON map in the `build-environment` **secret**. Values
are parsed without shell interpolation and passed only to the installer build
subprocess; the JSON carrier is removed from that subprocess's environment.
Do not pass all repository secrets with `toJSON(secrets)` or `secrets: inherit`.
Nonsecret `environment-json` provides single-line environment values to package
steps, including Mountlet's preview/production channel. macOS deployment target
defaults to 11.0. The workflow currently uses ad-hoc Apple signing; protected
publisher signing/notarization needs a separate reviewed extension.

## APT publication

`artifact-inputs` is a JSON object mapping artifact names to destination folders.
The workflow downloads artifacts from the caller's current run; optional
`source-run-id` supports backfills. **The caller must validate an older run's
workflow, conclusion, event, branch/tag, and intended channel before calling.**
`prepare-command` runs from the repository root and must leave validated Debian
packages at `apt-packages/*.deb`. It owns app identity/version/architecture checks
and preview transformations. There is no rebuild or automatic repackaging in the
shared workflow. It uploads a seven-day `apt-packages` artifact in the current
run, then dispatches `apt-package` to `1100soft/1100` (or `dispatch-repository`)
with the existing `source_repository`, `run_id`, and `artifact` payload.
The explicit `APT_DISPATCH_TOKEN` must permit dispatch to that destination.
A successful dispatch does not confirm that the external APT index has updated.

## Repository responsibilities and rollout

Mountlet keeps its R2 upload driver/manifest, bucket credentials, preview/stable
rules, APT identity preparation, and app hooks. Website/release-system checks now
use the independent Node workflow. Cerberus keeps stable tag validation, draft
release assembly, promotion gates, app regression scripts, and its small callers.
Its former local `tauri-check.yml` and `tauri-package.yml` have moved here; only
the small caller workflows remain in Cerberus. Existing unrelated uncommitted
Cerberus work is preserved.

1. Review and push the CI checkpoint commit. Local consumer references cannot
   resolve on GitHub until that exact commit exists on the remote.
2. If CI is private, grant the intended organization repositories access under
   CI's Actions settings. Caller Actions policies must permit these workflows.
3. Push the consumer updates after the shared commit is accessible. Update branch
   protection/rulesets for any changed nested job names.
4. Run branch CI and manual packages for both apps on GitHub. Confirm artifacts,
   runtime probes, runner availability, Store tooling, and release/APT permissions.
   Exercise tag/release gates through the apps' existing release policies.
5. Future shared changes receive a new reviewed SHA; explicitly update consumers.

No remote settings, secrets, branch protection, releases, or deployments are
configured by this local migration. Hosted Windows/macOS builds and APT dispatch
require real GitHub runs; offline contract checks do not establish those results.

## Local validation

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
actionlint .github/workflows/*.yml
```

The offline suite exercises requested/missing/unsupported bundle outputs,
credential JSON handling and subprocess isolation, build failure propagation,
and artifact-download arguments and failures. Validate caller workflows with
`actionlint` alongside the shared workflows before changing their pins.

References: [GitHub reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows),
[composite actions](https://docs.github.com/en/actions/tutorials/create-actions/create-a-composite-action),
and [private workflow access](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations).
