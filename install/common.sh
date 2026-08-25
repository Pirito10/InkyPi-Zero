#!/bin/bash

# Shared variables and functions for install.sh, update.sh and uninstall.sh.
# Must be sourced after SCRIPT_DIR is set.

bold=$(tput bold)
normal=$(tput sgr0)
red=$(tput setaf 1)

APPNAME="inkypi"
INSTALL_PATH="/usr/local/$APPNAME"
BINPATH="/usr/local/bin"
VENV_PATH="$INSTALL_PATH/venv_$APPNAME"

SERVICE_FILE="$APPNAME.service"
SERVICE_FILE_SOURCE="$SCRIPT_DIR/$SERVICE_FILE"
SERVICE_FILE_TARGET="/etc/systemd/system/$SERVICE_FILE"

APT_REQUIREMENTS_FILE="$SCRIPT_DIR/debian-requirements.txt"
CHROMIUM_REQUIREMENTS_FILE="$SCRIPT_DIR/chromium-requirements.txt"
WEBKITGTK_REQUIREMENTS_FILE="$SCRIPT_DIR/webkitgtk-requirements.txt"
PIP_REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"

echo_success() {
  echo -e "$1 [\e[32m\xE2\x9C\x94\e[0m]"
}

echo_error() {
  echo -e "${red}$1${normal} [\e[31m\xE2\x9C\x98\e[0m]\n"
}

echo_header() {
  echo -e "${bold}$1${normal}"
}

show_loader() {
  local pid=$!
  local delay=0.1
  local spinstr='|/-\'
  printf "$1 [${spinstr:0:1}] "
  while ps a | awk '{print $1}' | grep -q "${pid}"; do
    local temp=${spinstr#?}
    printf "\r$1 [${temp:0:1}] "
    spinstr=${temp}${spinstr%"${temp}"}
    sleep ${delay}
  done
  if [[ $? -eq 0 ]]; then
    printf "\r$1 [\e[32m\xE2\x9C\x94\e[0m]\n"
  else
    printf "\r$1 [\e[31m\xE2\x9C\x98\e[0m]\n"
  fi
}

# Get OS release number, e.g. 11=Bullseye, 12=Bookworm, 13=Trixie
get_os_version() {
  echo "$(lsb_release -sr)"
}

setup_zramswap_service() {
  echo "Enabling and starting zramswap service."
  sudo apt-get install -y zram-tools > /dev/null
  echo -e "ALGO=zstd\nPERCENT=60" | sudo tee /etc/default/zramswap > /dev/null
  sudo systemctl enable --now zramswap
}

setup_earlyoom_service() {
  echo "Enabling and starting earlyoom service."
  sudo apt-get install -y earlyoom > /dev/null
  sudo systemctl enable --now earlyoom
}

#
# calendar renders HTML via a headless browser. Chromium requires NEON, which
# CPUs like the Pi Zero W's (ARMv6) lack and will fail with "Illegal instruction".
# Install WebKitGTK instead on those, since it works without NEON (just slower).
#
install_browser_dependencies() {
  if grep -qi neon /proc/cpuinfo 2>/dev/null; then
    echo "CPU con soporte NEON detectado, instalando Chromium."
    xargs -a "$CHROMIUM_REQUIREMENTS_FILE" sudo apt-get install -y > /dev/null &
    show_loader "\tInstalling Chromium. "
  else
    echo "CPU sin soporte NEON detectado, instalando WebKitGTK."
    xargs -a "$WEBKITGTK_REQUIREMENTS_FILE" sudo apt-get install -y > /dev/null &
    show_loader "\tInstalling WebKitGTK. "
  fi
}
