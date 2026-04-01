<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://brands.home-assistant.io/vestaboard/dark_logo.png">
  <img alt="Vestaboard logo" src="https://brands.home-assistant.io/vestaboard/logo.png" width="450px">
</picture>

# Vestaboard for Home Assistant

[![Release](https://img.shields.io/github/v/release/natekspencer/ha-vestaboard?style=for-the-badge)](https://github.com/natekspencer/ha-vestaboard/releases)
[![HACS Badge](https://img.shields.io/badge/HACS-default-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![Buy Me A Coffee/Beer](https://img.shields.io/badge/Buy_Me_A_☕/🍺-F16061?style=for-the-badge&logo=ko-fi&logoColor=white&labelColor=grey)](https://ko-fi.com/natekspencer)
[![Sponsor on GitHub](https://img.shields.io/badge/Sponsor_💜-6f42c1?style=for-the-badge&logo=github&logoColor=white&labelColor=grey)](https://github.com/sponsors/natekspencer)

![Downloads](https://img.shields.io/github/downloads/natekspencer/ha-vestaboard/total?style=flat-square)
![Latest Downloads](https://img.shields.io/github/downloads/natekspencer/ha-vestaboard/latest/total?style=flat-square)

Home Assistant integration for Vestaboard messaging displays.

## 🔐 Local API Access Required

To use this integration, you **must first request access to Vestaboard's Local API**. This is required to enable local communication with your Vestaboard device.

### ✅ How to Request Access

1. Visit [https://www.vestaboard.com/local-api](https://www.vestaboard.com/local-api).
2. Fill out the request form to apply for a Local API enablement token.
3. Once approved, you will receive a token that you'll need to configure this integration.

⚠️ **Note:** The integration will not function without this token. Be sure to complete this step before proceeding with setup.

## ⬇️ Installation

### HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=natekspencer&repository=ha-vestaboard&category=integration)

This integration is available in the default [HACS](https://hacs.xyz/) repository.

1. Use the **My Home Assistant** badge above, or from within Home Assistant, click on **HACS**
2. Search for `Vestaboard` and click on the appropriate repository
3. Click **DOWNLOAD**
4. Restart Home Assistant

### Manual

If you prefer manual installation:

1. Download or clone this repository
2. Copy the `custom_components/vestaboard` folder to your Home Assistant `custom_components` directory
3. Restart Home Assistant

> ⚠️ Manual installation will not provide automatic update notifications. HACS installation is recommended unless you have a specific need.

## ➕ Setup

Once installed, you can set up the integration by clicking on the following badge:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=vestaboard)

Alternatively:

1. Go to [Settings > Devices & services](https://my.home-assistant.io/redirect/integrations/)
2. In the bottom-right corner, select **Add integration**
3. Type `Vestaboard` and select the **Vestaboard** integration
4. Follow the instructions to add the integration to your Home Assistant

## ⚙️ Options

After this integration is set up, you can configure the color of your Vestaboard to adjust the image that is generated.

|          |                                       Black                                       |                                       White                                       |
| -------- | :-------------------------------------------------------------------------------: | :-------------------------------------------------------------------------------: |
| Flagship | <img alt="Flagship Black Connected" src="images/flagship-black.png" width="100%"> | <img alt="Flagship White Connected" src="images/flagship-white.png" width="100%"> |
| Note     |     <img alt="Note Black Connected" src="images/note-black.png" width="70%">      |     <img alt="Note White Connected" src="images/note-white.png" width="70%">      |

## 🎬 Actions

### `vestaboard.message` - Send a message to one or more Vestaboards

[![Open your Home Assistant instance and show your service developer tools with a specific action selected.](https://my.home-assistant.io/badges/developer_call_service.svg)](https://my.home-assistant.io/redirect/developer_call_service/?service=vestaboard.message)

#### Fields

| Field                | Name                       | Required | Description                                                                                                                                                                       |
| -------------------- | -------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `device_id`          | Device                     | ✅ Yes   | The Vestaboard device(s) to send the message to. Supports multiple devices.                                                                                                       |
| `message`            | Message                    | No       | Plain text message to display. Supports multiline input.                                                                                                                          |
| `justify`            | Justify                    | No       | Horizontal text alignment. Default: `center`. Options: `left`, `right`, `center`, `justified`.                                                                                    |
| `align`              | Align                      | No       | Vertical text alignment. Default: `center`. Options: `top`, `bottom`, `center`, `justified`.                                                                                      |
| `vbml`               | Vestaboard Markup Language | No       | Compose a static or dynamic message using [VBML](https://docs.vestaboard.com/docs/vbml). Overrides `message` when provided.                                                       |
| `strategy`           | Transition Strategy        | No       | Animation style when a new message is sent. Options: `classic`, `column`, `reverse-column`, `edges-to-center`, `row`, `diagonal`, `random`.                                       |
| `step_size`          | Step Size                  | No       | Number of columns/rows/bits to animate simultaneously. Range: 1–132. Leave blank to animate one at a time.                                                                        |
| `step_interval_ms`   | Step Interval              | No       | Delay (in milliseconds) between each animation step. Range: 1–3000 ms. Leave blank for immediate sequential activation.                                                           |
| `duration`           | Duration                   | No       | Display the message temporarily for the specified duration (in seconds). The board reverts to its previous persistent message when the duration expires. Range: 10–43200 seconds. |
| `bypass_quiet_hours` | Bypass Quiet Hours         | No       | If `true`, ignores quiet hours settings and sends the message immediately.                                                                                                        |

---

#### Examples

**Send a simple text message:**

```yaml
action: vestaboard.message
data:
  device_id: your_device_id
  message: "Hello, world!"
  justify: center
  align: center
```

**Send a temporary message with a transition animation:**

```yaml
action: vestaboard.message
data:
  device_id: your_device_id
  message: "Dinner is ready!"
  strategy: column
  step_interval_ms: 500
  duration: 120
```

**Send a dynamic VBML message:**

```yaml
action: vestaboard.message
data:
  device_id: your_device_id
  vbml: >
    {
      "props": { "hours": "07", "minutes": "35" },
      "components": [{
        "style": { "justify": "center", "align": "center" },
        "template": "{{ '{{hours}}:{{minutes}}' }}"
      }]
    }
```

Note: The outer "{{ }}" escapes the inner VBML template syntax in the example above.

**Send to multiple devices, bypassing quiet hours:**

```yaml
action: vestaboard.message
data:
  device_id:
    - device_id_1
    - device_id_2
  message: "Good morning!"
  bypass_quiet_hours: true
```

---

#### Notes

- Either `message` or `vbml` should be provided, but not both. `vbml` takes precedence if both are given.
- `step_size` and `step_interval_ms` only apply when a `strategy` is specified.
- `duration` is useful for transient alerts - the board will restore its last persistent message automatically after the duration expires.

---

## ❤️ Support Me

I maintain this Home Assistant integration in my spare time. If you find it useful, consider supporting development:

- 💜 [Sponsor me on GitHub](https://github.com/sponsors/natekspencer)
- ☕ [Buy me a coffee / beer](https://ko-fi.com/natekspencer)
- 💸 [PayPal (direct support)](https://www.paypal.com/paypalme/natekspencer)
- ⭐ [Star this project](https://github.com/natekspencer/ha-vestaboard)
- 📦 If you’d like to support in other ways, such as donating hardware for testing, feel free to [reach out to me](https://github.com/natekspencer)

If you don't already own a Vestaboard, please consider using my referral link below to get $200 off (as well as a $200 referral bonus to me in appreciation)!

[Save $200 off a Vestaboard](https://web.vestaboard.com/referral?vbref=ZWVLZW)

## 📈 Star History

[![Star History Chart](https://api.star-history.com/svg?repos=natekspencer/ha-vestaboard)](https://www.star-history.com/#natekspencer/ha-vestaboard)
