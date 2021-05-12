# mini-syndicate-py

This is a Python implementation of the Syndicate network protocol.

It does *not* yet offer a formal Actor or Facet implementation for
Python, nor any Syndicate DSL language extensions.

    pip install mini-syndicate

or

    git clone https://git.syndicate-lang.org/syndicate-lang/mini-syndicate-py
    cd mini-syndicate-py
    virtualenv -p python3 pyenv
    . pyenv/bin/activate
    pip install -r requirements.txt

## Running

Start a Syndicate broker (such as
[this one](https://git.syndicate-lang.org/syndicate-rs)) in one window.

Then, run

    python [chat.py](chat.py) tcp://localhost:8001#chat

several times in separate windows.
