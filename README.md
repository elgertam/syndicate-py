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

    ... rootcap=<ref "syndicate" [] #x"a6480df5306611ddd0d3882b546e1977"> ...

Then, run [chat.py](chat.py) several times in several separate windows:

    python chat.py \
        --address '<tcp "localhost" 8001>' \
        --cap '<ref "syndicate" [] #x"a6480df5306611ddd0d3882b546e1977">'
