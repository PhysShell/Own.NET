#!/usr/bin/env bash
# version-specific re-derivation (frozen rules E1/E2/E3/H-20) for the Npgsql versions the E2 consumers resolve
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
cd $S/lab/sc && python3 wholesrc.py Npgsql@9.0.4 Npgsql@10.0.0 && python3 derive_whole.py Npgsql@9.0.4 Npgsql@10.0.0
echo REDERIVE_DONE
