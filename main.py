import requests
import json
import time
from typing import List

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import HttpUrl
from schemas.request import PredictionRequest, PredictionResponse
from utils.logger import setup_logger
import xml.etree.ElementTree as ET


# Initialize
app = FastAPI()
logger = None

def search_yandex(query_text, api_key, folder_id):
    url = "https://yandex.ru/search/xml"  # Пример эндпоинта (уточните у Yandex)
    headers = {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "query": {
            "searchType": "web",  
            "queryText": query_text,  
            "familyMode": "false", 
            "page": 0,  
            "fixTypoMode": "true"  
        },
        "sortSpec": {
            "sortMode": "rlv", 
            "sortOrder": "desc"  
        },
        "groupSpec": {
            "groupMode": "flat",  
            "groupsOnPage": 3,  
            "docsInGroup": 1  
        },
        "maxPassages": 3,  # Максимум 3 пассажа
        "region": 2, 
        "l10N": "ru",  
        "folderId": folder_id, 
        "responseFormat": "json", 
        "userAgent": ""  
    }
    response = requests.post(url, headers=headers, data=json.dumps(data))
    if response.status_code == 200:
        return response.json()  # Возвращаем JSON-ответ
    else:
        return None
    
def determine_correct_answer(query, deepseek_api_key):

    prompt = f"Вопрос: {query}\n\nВыбери правильный вариант ответа (1, 2, 3 или 4) и верни только номер."
    response = generate_answer_with_deepseek(prompt, deepseek_api_key)
    try:
        return int(response.strip())
    except ValueError:
        return None

@app.on_event("startup")
async def startup_event():
    global logger
    logger = await setup_logger()


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()

    body = await request.body()
    await logger.info(
        f"Incoming request: {request.method} {request.url}\n"
        f"Request body: {body.decode()}"
    )

    response = await call_next(request)
    process_time = time.time() - start_time

    response_body = b""
    async for chunk in response.body_iterator:
        response_body += chunk

    await logger.info(
        f"Request completed: {request.method} {request.url}\n"
        f"Status: {response.status_code}\n"
        f"Response body: {response_body.decode()}\n"
        f"Duration: {process_time:.3f}s"
    )

    return Response(
        content=response_body,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )


@app.post("/api/request", response_model=PredictionResponse)
async def predict(body: PredictionRequest):
    try:
        await logger.info(f"Processing prediction request with id: {body.id}")
        # Здесь будет вызов вашей модели
        yandex_api_key = "AQVN0AW2sXoFSGvGtrJun4y24NBsRTrWPZNfD7ya"
        folder_id = "b1gqvivb2mft2ir3a8ds"

        yandex_results = search_yandex(body.id, yandex_api_key, folder_id)
        sources = []
        if yandex_results and "results" in yandex_results:
            sources = [result["url"] for result in yandex_results["results"]]
        else:
            await logger.warning(f"No results found for query: {body.query}")

        deepseek_api_key = "your-deepseek-api-key" 
        reasoning = generate_answer_with_deepseek(body.query, deepseek_api_key)
        if not reasoning:
            reasoning = "Не удалось сгенерировать ответ с использованием языковой модели."

        answer = determine_correct_answer(body.query, deepseek_api_key)
        response = PredictionResponse(
            id=body.id,
            answer=answer,
            reasoning=reasoning,
            sources=sources,
        )
        await logger.info(f"Successfully processed request {body.id}")
        return response
    except ValueError as e:
        error_msg = str(e)
        await logger.error(f"Validation error for request {body.id}: {error_msg}")
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        await logger.error(f"Internal error processing request {body.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
