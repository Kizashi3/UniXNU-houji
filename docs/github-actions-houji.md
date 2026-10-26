# houji macOS kernel build

The Ubuntu preparation stage cannot run the Xcode kernel recipe. The workflow
`.github/workflows/houji-kernel.yml` runs the same build on GitHub's `macos-26`
runner and uploads the resulting `kernel.macho` and text logs as an artifact.

1. Put this device repository in GitHub. Keep Apple IPSW files and kernelcaches
   out of the repository; the workflow reads the pinned public IPSW URL in
   `board.toml` with range requests.
2. Open **Actions → houji XNU kernel → Run workflow** and keep Xcode `26.6`.
3. Download the artifact named `houji-xnu-kernel-<run number>`.

The workflow uses iPhone10,3 / iPhone10,6 iOS 16.7.16 (20H392), the board
identity recorded in `board.toml`. The decoded kernelcache hash is deliberately
left unset until the first macOS extraction is verified; it should then be
recorded in `[kernel.prelink]`.
