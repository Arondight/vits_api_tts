import html
import re
import requests
import gradio as gr

from datetime import datetime
from pathlib import Path
from modules import chat, shared, ui_chat
from modules.logging_colors import logger
from modules.utils import gradio

params = {
    "activate": False,
    "autoplay": False,
    "base_url": "http://localhost:23456/",
    "length": "1.3",
    "noise": "0.4",
    "noisew": "0.5",
    "selected_voice": None,
    "show_text": True,
    "streaming": False,
}
voices = None


def refresh_voices():
    global params

    if params["base_url"] is not None:
        url = f"{params['base_url']}/voice/speakers"

        try:
            res = requests.get(url=url)
            json = res.json()
            api_voices = json["VITS"]
            voice_names = [f"{voice['id']} | {voice['name']} | {'/'.join(voice['lang'])}" for voice in api_voices]
        except:
            voice_names = ["0.default"]

    return voice_names


def refresh_voices_dd():
    all_voices = refresh_voices()

    return gr.Dropdown.update(value=all_voices[0], choices=all_voices)


def remove_tts_from_history(history):
    for i, entry in enumerate(history["internal"]):
        history["visible"][i] = [history["visible"][i][0], entry[1]]

    return history


def toggle_text_in_history(history):
    for i, entry in enumerate(history["visible"]):
        visible_reply = entry[1]

        if visible_reply.startswith("<audio"):
            if params["show_text"]:
                reply = history["internal"][i][1]
                history["visible"][i] = [
                    history["visible"][i][0],
                    f"{visible_reply.split('</audio>')[0]}</audio>\n\n{reply}",
                ]
            else:
                history["visible"][i] = [
                    history["visible"][i][0],
                    f"{visible_reply.split('</audio>')[0]}</audio>",
                ]

    return history


def remove_surrounded_chars(string):
    # this expression matches to 'as few symbols as possible (0 upwards) between any asterisks' OR
    # 'as few symbols as possible (0 upwards) between an asterisk and the end of the string'
    return re.sub("\*[^\*]*?(\*|$)", "", string)


def state_modifier(state):
    if params["activate"]:
        state["stream"] = False

    return state


def input_modifier(string):
    if params["activate"]:
        shared.processing_message = "*Waiting ...*"

    return string


def history_modifier(history):
    # Remove autoplay from the last reply
    if len(history["internal"]) > 0:
        history["visible"][-1] = [
            history["visible"][-1][0],
            history["visible"][-1][1].replace("controls autoplay>", "controls>"),
        ]

    return history


def output_modifier(string):
    global params

    if not params["activate"]:
        return string

    original_string = html.unescape(string)
    string = remove_surrounded_chars(original_string) # Apply remove_surrounded_chars after unescaping to ensure patterns are correctly matched in the decoded string

    # XXX I'm not sure what I'm doing here
    replace = {'"': "", "“": "", "”": "", "‘": "", "’": "", "(": "", "（": "", ")": "", "）": "", "\n": " "} # Deleted "'": "", it is buggy

    for k, v in replace.items():
        string = string.replace(k, v)

    string = string.strip()

    if 0 == len(string):
        return string

    # Sanitize the output filename?
    output_dir = Path("extensions/vits_api_tts/outputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y-%m-%dT%H-%M-%S.%fZ')
    output_file = output_dir / f"{timestamp}.mp3"
    
    id = params["selected_voice"].split(" | ")[0]
    fields = {
        "text": string,
        "id": str(id),
        "segment_size": "0", # Improves output quality
        "format": "mp3",
        "lang": "auto",
        "length": str(params["length"]),
        "noise": str(params["noise"]),
        "noisew": str(params["noisew"]),
        "streaming": str(params["streaming"]),
    }
    url = f"{params['base_url']}/voice/vits"
    res = requests.get(url=url, params=fields)

    with open(output_file, "wb") as f:
        f.write(res.content)

    autoplay = "autoplay" if params["autoplay"] else ""
    string = f'<audio src="file/{output_file.as_posix()}" controls {autoplay}></audio>'

    if params["show_text"]:
        string += f"\n\n{original_string}"

    shared.processing_message = "*Waiting ...*"

    return string


def ui():
    global voices

    if not voices:
        voices = refresh_voices()
        selected = params["selected_voice"]

        if selected is None or selected not in voices:
            params["selected_voice"] = voices[0]

        logger.info(f"Set voice to {params['selected_voice']}")

    # Gradio elements
    with gr.Row():
        activate = gr.Checkbox(value=params["activate"], label="Activate TTS")
        autoplay = gr.Checkbox(value=params["autoplay"], label="Play TTS automatically")
        show_text = gr.Checkbox(value=params["show_text"], label="Show message text under audio player")

    with gr.Row():
        streaming = gr.Checkbox(value=params["streaming"], label="Streaming Response (recommended not to set)")
        length = gr.Textbox(value=params["length"], label="Syllable Length")
        noise = gr.Textbox(value=params["noise"], label="Sample Noise")
        noisew = gr.Textbox(value=params["noisew"], label="Random Market Predictor Noise")

    with gr.Row():
        voice = gr.Dropdown(value=params["selected_voice"], choices=voices, label="TTS Voice")
        refresh = gr.Button(value="Refresh")

    with gr.Row():
        base_url = gr.Textbox(value=params["base_url"], label="Base URL")
        params.update({"base_url": params["base_url"]})

    with gr.Row():
        convert = gr.Button("Permanently replace audios with the message texts")
        convert_cancel = gr.Button("Cancel", visible=False)
        convert_confirm = gr.Button("Confirm (cannot be undone)", variant="stop", visible=False)

    # Convert history with confirmation
    convert_arr = [convert_confirm, convert, convert_cancel]

    convert.click(
        lambda: [
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(visible=True),
        ],
        None,
        convert_arr,
    )
    convert_confirm.click(
        lambda: [
            gr.update(visible=False),
            gr.update(visible=True),
            gr.update(visible=False),
        ],
        None,
        convert_arr,
    ).then(remove_tts_from_history, gradio("history"), gradio("history")).then(
        chat.save_history,
        gradio("history", "unique_id", "character_menu", "mode"),
        None,
    ).then(
        chat.redraw_html, gradio(ui_chat.reload_arr), gradio("display")
    )
    convert_cancel.click(
        lambda: [
            gr.update(visible=False),
            gr.update(visible=True),
            gr.update(visible=False),
        ],
        None,
        convert_arr,
    )

    # Toggle message text in history
    show_text.change(lambda x: params.update({"show_text": x}), show_text, None).then(
        toggle_text_in_history, gradio("history"), gradio("history")
    ).then(
        chat.save_history,
        gradio("history", "unique_id", "character_menu", "mode"),
        None,
    ).then(
        chat.redraw_html, gradio(ui_chat.reload_arr), gradio("display")
    )

    # Event functions to update the parameters in the backend
    activate.change(lambda x: params.update({"activate": x}), activate, None)
    voice.change(lambda x: params.update({"selected_voice": x}), voice, None)
    streaming.change(lambda x: params.update({"streaming": x}), streaming, None)
    length.change(lambda x: params.update({"length": x}), length, None)
    noise.change(lambda x: params.update({"noise": x}), noise, None)
    noisew.change(lambda x: params.update({"noisew": x}), noisew, None)
    base_url.change(lambda x: params.update({"base_url": x}), base_url, None)
    refresh.click(refresh_voices_dd, [], voice)
    autoplay.change(lambda x: params.update({"autoplay": x}), autoplay, None)
