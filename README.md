[![Release](https://img.shields.io/github/v/release/natekspencer/ha-vestaboard?style=for-the-badge)](https://github.com/natekspencer/ha-vestaboard/releases)
[![Buy Me A Coffee/Beer](https://img.shields.io/badge/Buy_Me_A_☕/🍺-F16061?style=for-the-badge&logo=ko-fi&logoColor=white&labelColor=grey)](https://ko-fi.com/natekspencer)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

![Downloads](https://img.shields.io/github/downloads/natekspencer/ha-vestaboard/total?style=flat-square)
![Latest Downloads](https://img.shields.io/github/downloads/natekspencer/ha-vestaboard/latest/total?style=flat-square)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://brands.home-assistant.io/vestaboard/dark_logo.png">
  <img alt="Vestaboard logo" src="https://brands.home-assistant.io/vestaboard/logo.png">
</picture>

# Vestaboard for Home Assistant

Home Assistant integration for Vestaboard messaging displays.

## 🔐 Local API Access Required

To use this integration, you **must first request access to Vestaboard's Local API**. This is required to enable local communication with your Vestaboard device.

### ✅ How to Request Access

1. Visit [https://www.vestaboard.com/local-api](https://www.vestaboard.com/local-api).
2. Fill out the request form to apply for a Local API enablement token.
3. Once approved, you will receive a token that you'll need to configure this integration.

⚠️ **Note:** The integration will not function without this token. Be sure to complete this step before proceeding with setup.

# Installation

There are two main ways to install this custom component within your Home Assistant instance:

1. Using HACS (see https://hacs.xyz/ for installation instructions if you do not already have it installed):

   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=natekspencer&repository=ha-vestaboard&category=integration)
   1. Use the convenient My Home Assistant link above, or, from within Home Assistant, click on the link to **HACS**
   2. Click on **Integrations**
   3. Click on the vertical ellipsis in the top right and select **Custom repositories**
   4. Enter the URL for this repository in the section that says _Add custom repository URL_ and select **Integration** in the _Category_ dropdown list
   5. Click the **ADD** button
   6. Close the _Custom repositories_ window
   7. You should now be able to see the _Vestaboard_ card on the HACS Integrations page. Click on **INSTALL** and proceed with the installation instructions.
   8. Restart your Home Assistant instance and then proceed to the _Configuration_ section below.

2. Manual Installation:
   1. Download or clone this repository
   2. Copy the contents of the folder **custom_components/vestaboard** into the same file structure on your Home Assistant instance
      - An easy way to do this is using the [Samba add-on](https://www.home-assistant.io/getting-started/configuration/#editing-configuration-via-sambawindows-networking), but feel free to do so however you want
   3. Restart your Home Assistant instance and then proceed to the _Configuration_ section below.

While the manual installation above seems like less steps, it's important to note that you will not be able to see updates to this custom component unless you are subscribed to the watch list. You will then have to repeat each step in the process. By using HACS, you'll be able to see that an update is available and easily update the custom component.

# Configuration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=vestaboard)

There is a config flow for this Vestaboard integration. After installing the custom component, use the convenient My Home Assistant link above.

Alternatively:

1. Go to **Configuration**->**Integrations**
2. Click **+ ADD INTEGRATION** to setup a new integration
3. Search for **Vestaboard** and click on it
4. You will be guided through the rest of the setup process via the config flow

# Options

After this integration is set up, you can configure the model of your Vestaboard to adjust the image that is generated.

Models:

- Flagship Black
  ![Flagship Black Connected](images/flagship.png)
- Vestaboard White
  ![Vestaboard White Connected](images/white.png)

---

## Support Me

I'm not employed by Vestaboard, and provide this custom component purely for your own enjoyment and home automation needs.

If you don't already own a Vestaboard, please consider using my referal link below to get $200 off (as well as a $200 referral bonus to me in appreciation)!

https://web.vestaboard.com/referral?vbref=ZWVLZW

If you already own a Vestaboard and still want to donate, consider [sponsoring me on GitHub](https://github.com/sponsors/natekspencer) or buying me a coffee ☕ (or beer 🍺) instead by using the link below:

<a href='https://ko-fi.com/Y8Y57F59S' target='_blank'><img height='36' style='border:0px;height:36px;' src='https://storage.ko-fi.com/cdn/kofi1.png?v=3' border='0' alt='Buy Me a Coffee at ko-fi.com' /></a>
