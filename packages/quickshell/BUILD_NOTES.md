# Draft first-release runtime package

Decision: keep Omarchy’s pinned Quickshell QML-loader patch for the first release, using upstream Qt6 packages. This does not patch Qt itself and does not use the Omarchy package repository.

The recipe is adapted from `omacom/omarchy-pkgs` commit `bed2ea5a48400c02228c86dd4da9bc75487a24ee`, directory `pkgbuilds/quickshell/`:

- Package renamed to `v8-quickshell`.
- Provides the versioned `quickshell` capability and conflicts with other packages owning the same runtime files.
- Keeps Quickshell commit `2b4501a282689792b62e94f3fb30d8f512324fe6` and the original patch bytes.
- Uses a stable source directory named `quickshell` after the package rename.
- Changes distributor metadata to V8, gives the compatibility hook a project-specific filename and includes qt6-declarative in its diagnostic triggers to match the declared rebuild inputs.

The source is pinned by Git commit. As in the source recipe, the VCS source has `SKIP` in the makepkg checksum array; this is not a locally verified release signature. Patch and hook file checksums are recorded and must match. A release pipeline should additionally record the actual source tree, complete dependency package hashes, build options, build results and signed package output.

Checks completed: patch applicability against the pinned source without applying it; PKGBUILD syntax using `bash -n`. No recipe sourcing, compilation, package installation or runtime test has been performed. Build only in an appropriate disposable Arch/ALARM environment, with native/target-architecture toolchain and declared dependencies.

Rebuild on changes to Qt base, declarative or Wayland. The historical Omarchy recipe records Qt 6.12 inputs; those values describe an earlier build and are not a supported downgrade recipe. Verify an entire current target package transaction and all QML surfaces, including lock/PAM/polkit, rather than pinning one Qt library independently.

`runtime.lock.json` records provenance and validation status. It is an audit/build-input record, not a toolchain lock that alone makes the binary reproducible.
