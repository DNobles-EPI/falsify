## INIT
read -p "Git name: " GIT_NAME
read -p "Git email: " GIT_EMAIL


### INSTALLS
# update existing pkgs to latest
sudo apt update
sudo apt upgrade -y

# install curl
sudo apt install curl -y

# install GitHub CLI
sudo apt install gh -y

# install Node.js
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt install nodejs -y

# install codex
npm i -g @openai/codex

### LOGIN
# login to stuff
git config --global user.name "$GIT_NAME"
git config --global user.email "$GIT_EMAIL"
gh auth login
codex login

### REPO STUFF
# make & enter project dir
mkdir projects
cd projects

# clone some repo, eg:
gh repo clone sontric/falsify

# run an agent or whatever
fals