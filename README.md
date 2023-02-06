# syndicate-py

This is a Python implementation of Syndicated Actors and the Syndicate network protocol.

    pip install syndicate-py

or

    git clone https://git.syndicate-lang.org/syndicate-lang/syndicate-py
    cd syndicate-py
    virtualenv -p python3 pyenv
    . pyenv/bin/activate
    pip install -r requirements.txt

## Running

Start a Syndicate broker (such as
[this one](https://git.syndicate-lang.org/syndicate-rs)) in one window.

Find the line of broker output giving the root capability:

    ... rootcap=<ref "syndicate" [] #x"69ca300c1dbfa08fba692102dd82311a"> ...

Then, run [chat.py](chat.py) several times in several separate windows:

    python chat.py \
        --address '<tcp "localhost" 8001>' \
        --cap '<ref "syndicate" [] #x"69ca300c1dbfa08fba692102dd82311a">'
