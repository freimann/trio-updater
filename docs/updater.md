# Trio Updater — application analysis

Analyzed artifact: `trioupdaterinstaller_v2.0.2.exe`
(SHA-256 in `reference/artifacts.sha256`).

## Installer contents

Inno Setup 5.5.7 package. Extracted contents:

```
app/TrioUpdater.exe        Qt5 GUI (x86, MSVC)
app/Qt5Core.dll, Qt5Gui.dll, Qt5Network.dll, Qt5Svg.dll, Qt5Widgets.dll, Qt5Xml.dll
app/ISSkin.dll             Inno Setup skinning
app/TrioUpdater.lib        import library (shipped by mistake)
app/TrioUpdater.exp
app/bearer/, imageformats/, iconengines/, platforms/
vcredist
```

**There is no firmware in the installer.** All device images are fetched at
runtime.

## Device detection

`FUN_0040ef50` enumerates HID devices with vendor ID `0x1210` (product ID
filter `0`), then branches on the product ID:

| PID | Model value | Product |
|---|---|---|
| `0x0042` | 0 | Trio |
| `0x0043` | 1 | Trio+ |

`FUN_0040de40` builds the device-info panel from that model value
(`0 -> "Trio"`, `1 -> "Trio+"`, with a `Styles:` line only for the Trio+).
`FUN_00409430` resolves the per-model component list from the manifest.

Consequence for modding: the updater will still find a modified unit as long as
the VID/PID pair is preserved. Changing the PID would require patching the app
too.

## Manifest

Default URL (string at `0x41ef5c`, used by `FUN_00416ad0`):

```
http://harmandbx.blob.core.windows.net/digi-trio-plus/tp-manifest.xml
```

Stored via QSettings under `update/manifest-url`, overridable at runtime with
the **"Set Manifest URL…"** action. The manifest is still served (snapshot in
`reference/tp-manifest.xml`, `Last-Modified: 2017-09-21`).

Structure:

```xml
<Family Name="TRIO" ID="0x63">
  <Product Name="TRIO+" ID="0x43">
    <Component Name="MP"       Version="3.1.0"  URL=".../TrioPlus/TrioLooper_Update.bin"/>
    <Component Name="DSP"      Version="3.3.1"  URL=".../TrioPlus/DSP1.ldr"/>
    <Component Name="Ensemble" Version="0xD53C" URL=".../TrioPlus/EnsembleAudio.flac"/>
    <Component Name="Styles"   Version="0xF7D6" URL=".../TrioPlus/TrioPlusStyleData.bin"/>
  </Product>
  <Product Name="TRIO" ID="0x42">
    <Component Name="MP"  Version="3.1.4" URL=".../OriginalTrio/Trio_Update.bin"/>
    <Component Name="DSP" Version="3.3.0" URL=".../OriginalTrio/DSP1.ldr"/>
  </Product>
  <Product Name="Trio Updater">  <Component Name="Win" .../> <Component Name="Mac" .../> </Product>
  <Product Name="Trio Manager">  <Component Name="Win" .../> <Component Name="Mac" .../> </Product>
</Family>
```

Components are considered updatable when the manifest `Version` is newer than
what the device reports. Because both the manifest URL and the per-component
URLs are user-controlled, a modified manifest served from any HTTP host is
enough to flash a custom image with the **stock** updater — no app patching.

## Relevant functions

| Address | Role |
|---|---|
| `FUN_0040ef50` | HID device enumeration, model detection |
| `FUN_0040de40` | Device info UI (`Trio` / `Trio+`) |
| `FUN_00416ad0` | Manifest URL, download |
| `FUN_00411a80` | Component download |
| `FUN_00409430` | Component/update list per model |
| `FUN_00401460` | DSP flasher |
| `FUN_00401d40` | MP (MCU) flasher |
| `FUN_00401800` | Ensemble audio flasher |
| `FUN_00402040` | Styles flasher |
| `FUN_004011d0` | "Ready" query |

The flasher routines are statically linked reference C code and still contain
their `printf` debug strings (`"Sending Micro FW: %s\n"`, `"Checksum = %8.8X\n"`,
`"Sending terminating packet...\n"`), which is what makes the protocol easy to
reconstruct from the app.
