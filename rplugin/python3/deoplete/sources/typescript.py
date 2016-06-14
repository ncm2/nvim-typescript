import os
import re
import json
import subprocess
import platform
import itertools

from threading import Thread
from threading import Event
from threading import Lock

from tempfile import NamedTemporaryFile
from deoplete.sources.base import Base

MAX_COMPLETION_DETAIL = 50
RESPONSE_TIMEOUT_SECONDS = 20


class Source(Base):

    # Base options
    def __init__(self, vim):
        Base.__init__(self, vim)

        # Deoplete related
        self.debug_enabled = True
        self.name = "typescript"
        self.filetypes = ["typescript"]
        self.mark = "TS"
        self.rank = 700
        self.input_pattern = r'\.\w*'
        # self.input_pattern = '.'

        # Project related
        self._project_directory = os.getcwd()
        self._sequenceid = 0
        self._environ = os.environ.copy()
        self._tsserver_handle = subprocess.Popen("tsserver",
                                                 env=self._environ,
                                                 cwd=self._project_directory,
                                                 stdout=subprocess.PIPE,
                                                 stdin=subprocess.PIPE,
                                                 stderr=subprocess.STDOUT,
                                                 universal_newlines=True,
                                                 shell=True,
                                                 bufsize=1)

    def search_tss_project_dir(self, context):
        self._project_directory = context['cwd']

    def _sendReuest(self, command, arguments=None, wait_for_response=False):
        seq = self._next_sequence_id()
        request = {
            "seq":     seq,
            "type":    "request",
            "command": command
        }
        if arguments:
            request["arguments"] = arguments

        self._write_message(request)

        if not wait_for_response:
            return

        linecount = 0
        headers = {}
        while True:
            headerline = self._tsserver_handle.stdout.readline().strip()
            linecount += 1
            if len(headerline):
                key, value = headerline.split(":", 2)
                headers[key.strip()] = value.strip()
                break
        if "Content-Length" not in headers:
            raise RuntimeError("Missing 'Content-Length' header")
        contentlength = int(headers["Content-Length"])
        return json.loads(self._tsserver_handle.stdout.read(contentlength))

    # take the command build-up, and post it subprocess
    def _write_message(self, message):
        self._tsserver_handle.stdin.write(json.dumps(message))
        self._tsserver_handle.stdin.write("\n")

    def _reload(self):
        filename = self.relative_file()
        contents = self.vim.eval("join(getline(1,'$'), \"\n\")")
        tmpfile = NamedTemporaryFile(delete=False)
        tmpfile.write(contents.encode('utf-8'))
        tmpfile.close()
        self._sendReuest('reload', {
            'file': filename,
            'tmpfile': tmpfile.name
        }, wait_for_response=True)
        # os.unlink(tmpfile.name)

    def relative_file(self):
        return self.vim.eval("expand('%:p')")

    def _next_sequence_id(self):
        seq = self._sequenceid
        self._sequenceid += 1
        return seq

    def on_event(self, context):
        # if context['event'] == 'BufEnter':
        self.debug('BUFENTER')
        self._sendReuest('open', {'file': self.relative_file()})

    # Get cursor position in the buffer
    def get_complete_position(self, context):
        m = re.search(r"\w*$", context["input"])
        return m.start() if m else -1

    def gather_candidates(self, context):
        self._reload()
        data = self._sendReuest("completions", {
            "file":   self.relative_file(),
            "line":   context["position"][1],
            "offset": context["complete_position"] + 1,
            "prefix": context["complete_str"]
        }, wait_for_response=True)

        self.debug('*' * 25)
        self.debug(data)
        self.debug('*' * 25)

        if data is None or not "body" in data:
            return []
        # if there are too many entries, just return basic completion
        # if len(data["body"]) > MAX_COMPLETION_DETAIL:
        return [self._convert_completion_data(e) for e in data["body"]]

        # build up more helpful completion data
        # names = []
        # maxNameLength = 0
        # for entry in data["body"]:
        #     names.append(entry["name"])
        #     maxNameLength = max(maxNameLength, len(entry["name"]))
        #
        # detailed_data = self._sendReuest('completionEntryDetails', {
        #     "file":   self.relative_file(),
        #     "line":   context["position"][1],
        #     "offset": context["complete_position"],
        #     "entryNames": names
        # }, wait_for_response=True)

        # if detailed_data is None or not "body" in detailed_data:
        # return []

        # return [self._convert_detailed_completion_data(e, padding=maxNameLength)
        # for e in detailed_data["body"]]

    # If the results are over 100, return a simplified list
    def _convert_completion_data(self, entry):
        return {
            "word": entry["name"],
            "kind": entry["kind"]
            # "menu": entry["kindModifiers"]
            # "info": menu_text
        }

    # Under 100, provide more detail
    # TODO: Send method signature to preview window
    def _convert_detailed_completion_data(self, entry, padding=80):
        # self.debug(entry)

        name = entry["name"]
        # display_parts = entry['displayParts']
        # signature = ''.join([p['text'] for p in display_parts])

        # needed to strip new lines and indentation from the signature
        # signature = re.sub( '\s+', ' ', signature )
        # menu_text = '{0} {1}'.format(name.ljust(padding), signature)
        return ({
            "word": name,
            "kind": entry["kind"],
            # "info": menu_text
        })