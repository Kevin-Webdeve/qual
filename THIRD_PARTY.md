# Third-party software

This application uses these projects. Their respective licenses apply to their components.

- Python: PSF license — https://docs.python.org/3/license.html
- Tcl/Tk: Tcl/Tk license — https://www.tcl-lang.org/software/tcltk/license.html
- Pillow: MIT-CMU — https://github.com/python-pillow/Pillow/blob/main/LICENSE
- imageio-ffmpeg: BSD-2-Clause — https://github.com/imageio/imageio-ffmpeg/blob/main/LICENSE
- FFmpeg: https://www.ffmpeg.org/legal.html — this bundled build includes GPL components. Build version, configuration and license text can be inspected by running the bundled FFmpeg executable with `-version`, `-buildconf`, and `-L`.
- x264: GPL — https://www.videolan.org/developers/x264.html
- PyInstaller bootloader: GPL with a distribution exception — https://pyinstaller.org/en/stable/license.html
- Node.js: MIT and bundled third-party licenses — bundled `vendor/node/LICENSE`, also copied to the portable `licenses` folder. Official source and releases: https://nodejs.org/ and https://github.com/nodejs/node.
- CompressBase public local SL/SR helper: https://compressbase.com/method-api/sl-sr.mjs — offered for local use/self-hosting by https://compressbase.com/method-api. The helper is bundled without changes. The app displays the required visible **Powered by CompressBase** link beside the method tool and preserves the `Patched by Compressbase` output comment. It does not call or provide access to the protected legacy patch API. Download URL, helper SHA256, and Node archive provenance are recorded in `vendor/method-provenance.json`.

FFmpeg source: https://git.ffmpeg.org/ffmpeg.git

The bundled FFmpeg 9.0.2 essentials binary is supplied by the imageio-ffmpeg Windows wheel and identifies its upstream builder as www.gyan.dev. Build information and source links: https://www.gyan.dev/ffmpeg/builds/ and https://github.com/imageio/imageio-ffmpeg. Review the exact binary configuration before redistribution. This project does not change FFmpeg's source code.
