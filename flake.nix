{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            python3
            poetry
            allure
            stdenv.cc.cc.lib  # needed b/c I'm keeping nix env deps separate from python deps (numpy needs this via poetry)
            graphviz
          ];
        
          shellHook = ''
            export LD_LIBRARY_PATH=${pkgs.lib.makeLibraryPath [
              pkgs.stdenv.cc.cc.lib
              pkgs.zlib
            ]}:$LD_LIBRARY_PATH

            # Ensure Poetry uses an in-project virtualenv: ./.venv
            export POETRY_VIRTUALENVS_IN_PROJECT=true

            sync_required=false
            if [ ! -f .venv/bin/activate ]; then
              echo "[nix] creating Poetry venv + installing deps..."
              sync_required=true
            elif [ pyproject.toml -nt .venv ] || { [ -f poetry.lock ] && [ poetry.lock -nt .venv ]; }; then
              echo "[nix] pyproject/lock changed -> syncing deps..."
              sync_required=true
            fi

            if [ "$sync_required" = true ]; then
              poetry env use "${pkgs.python3}/bin/python"
              poetry install --no-interaction
              # Keep a simple timestamp anchor for staleness checks.
              touch .venv
            fi

            # Activate the Poetry venv for this shell.
            . .venv/bin/activate
            export PATH="$PWD/.venv/bin:$PATH"
            export PYTHONNOUSERSITE=1
          '';
        };
      });
}
