import os
import time

import uvicorn
import json
import requests

from fastapi import FastAPI
from fastapi.background import BackgroundTasks
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from typing import Any, Optional

from loguru import logger

load_dotenv()

from utils.aily_ctl import AilyCtl
from utils.config_ctl import ConfigCtl
from utils.device_ctl import DeviceCtl

aily_ctl = AilyCtl()
conf_ctl = ConfigCtl()
device_ctl = DeviceCtl()


class ResponseModel(BaseModel):
    status: int = 200
    message: str = "success"
    data: Any = None


class ModelDataUpdate(BaseModel):
    llmURL: Optional[str] = ""
    llmModel: Optional[str] = ""
    llmKey: Optional[str] = ""
    llmPrePrompt: Optional[str] = ""
    llmTemp: Optional[str] = ""
    sttURL: Optional[str] = ""
    sttModel: Optional[str] = ""
    sttKey: Optional[str] = ""
    ttsURL: Optional[str] = ""
    ttsModel: Optional[str] = ""
    ttsKey: Optional[str] = ""
    ttsRole: Optional[str] = ""


class AsrReqData(BaseModel):
    wakeKeyword: str


app = FastAPI()

# 配置跨域相关策略
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"


@app.get(f"{API_PREFIX}/ping")
async def get_ping():
    return ResponseModel(data="pong")


@app.get(f"{API_PREFIX}/logs")
async def get_logs(
        page: int = 1,
        perPage: int = 10,
):
    aily_ctl.log_cur_page = page
    res = aily_ctl.get_logs(perPage)
    data = []
    if res:
        for item in res:
            data.append(
                {
                    "role": "user" if item[0] == "tool" else item[0],
                    "msg": (
                        json.loads(item[1])["url"] if item[2] == "image" else item[1]
                    ),
                    "type": item[2] if item[2] else "text",
                }
            )

    return ResponseModel(data={"page": page, "perPage": perPage, "list": data})


@app.get(f"{API_PREFIX}/llmModelOptions")
async def get_llm_model_options():
    return ResponseModel(data=conf_ctl.get_llm_models())


@app.get(f"{API_PREFIX}/sttModelOptions")
async def get_stt_model_options():
    return ResponseModel(data=conf_ctl.get_stt_models())


@app.get(f"{API_PREFIX}/ttsModelOptions")
async def get_tts_model_options():
    return ResponseModel(data=conf_ctl.get_tts_models())


@app.get(f"{API_PREFIX}/modelData")
async def get_model_data():
    return ResponseModel(
        data={
            "llmURL": aily_ctl.get_llm_url(),
            "llmModel": aily_ctl.get_llm_model(),
            "llmKey": aily_ctl.get_llm_key(),
            "llmPrePrompt": aily_ctl.get_llm_preprompt(),
            "llmTemp": aily_ctl.get_llm_temp(),
            "sttURL": aily_ctl.get_stt_url(),
            "sttModel": aily_ctl.get_stt_model(),
            "sttKey": aily_ctl.get_stt_key(),
            "ttsURL": aily_ctl.get_tts_url(),
            "ttsModel": aily_ctl.get_tts_model(),
            "ttsKey": aily_ctl.get_tts_key(),
            "ttsRole": aily_ctl.get_tts_role(),
        }
    )


@app.post(f"{API_PREFIX}/modelData")
async def set_model_data(
        data: ModelDataUpdate,
):
    aily_ctl.set_llm_url(data.llmURL)
    aily_ctl.set_llm_model(data.llmModel)
    aily_ctl.set_llm_key(data.llmKey)
    aily_ctl.set_llm_preprompt(data.llmPrePrompt)
    aily_ctl.set_llm_temp(data.llmTemp)
    aily_ctl.set_stt_url(data.sttURL)
    aily_ctl.set_stt_model(data.sttModel)
    aily_ctl.set_stt_key(data.sttKey)
    aily_ctl.set_tts_url(data.ttsURL)
    aily_ctl.set_tts_model(data.ttsModel)
    aily_ctl.set_tts_key(data.ttsKey)
    aily_ctl.set_tts_role(data.ttsRole)

    aily_ctl.save("reload")

    return ResponseModel()


def req_gen_firmware(data: dict):
    server = os.environ.get("FIRMWARE_SERVER")
    url = f"{server}/api/v1/asr"
    # 发起生成请求
    res = requests.post(url, json=data)
    if res.status_code != 200:
        logger.error(f"生成固件失败: {res.text}")
        return None

    req_data = res.json()
    gen_id = req_data["data"]["id"]

    return gen_id


def req_gen_status(gen_id: str):
    server = os.environ.get("FIRMWARE_SERVER")
    url = f"{server}/api/v1/firmware/status?prj_name={gen_id}"
    # 发起状态获取请求
    res = requests.get(url)
    if res.status_code != 200:
        logger.error(f"获取固件生成状态失败: {res.text}")
        return None

    req_data = res.json()
    return req_data["data"]["status"]


def req_download_firmware(gen_id: str):
    server = os.environ.get("FIRMWARE_SERVER")
    url = f"{server}/api/v1/firmware/download?prj_name={gen_id}"
    # 发起下载请求
    res = requests.get(url)
    if res.status_code != 200:
        logger.error(f"下载固件失败: {res.text}")
        return None

    # 保存固件
    firmware_path_root = os.environ.get("FIRMWARE_PATH")
    save_path = f"{firmware_path_root}/{gen_id}.bin"
    with open(save_path, "wb") as f:
        f.write(res.content)

    return save_path


def get_firmware(gen_id: str):
    # 等待生成完成
    gen_result = False
    while True:
        time.sleep(5)
        gen_status = req_gen_status(gen_id)
        if gen_status == 3:
            logger.error(f"生成固件失败: {gen_id}")
            break
        elif gen_status == 2:
            logger.success(f"生成固件成功: {gen_id}")
            gen_result = True
            break
        else:
            continue

    if gen_result:
        # 下载固件
        download_path = req_download_firmware(gen_id)
        return download_path
    return None


@app.post(f"{API_PREFIX}/asr")
async def post_asr(
        data: AsrReqData,
        background_tasks: BackgroundTasks,
):
    gen_id = req_gen_firmware(data.dict())
    background_tasks.add_task(get_firmware, gen_id)
    return ResponseModel(data={"id": gen_id})


@app.get(f"{API_PREFIX}/asr/status")
async def get_asr_status(
        prj_name: str,
):
    return ResponseModel(data=req_gen_status(prj_name))


uvicorn.run(app, host="0.0.0.0", port=8888)
