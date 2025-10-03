from fastapi import HTTPException
import json
from fastapi.responses import StreamingResponse
import os, httpx, asyncio
from typing import List, Literal, Optional, Dict, Any

from logs.logging_config  import get_logger
from colorama import Fore, Style, init

logger = get_logger("AiClientService")


Provider = Literal["groq", "openrouter"]

class AiClientService():
    def __init__(self,
        default_provider: Provider = "groq",
        groq_model: Optional[str] = None,
        openrouter_model: Optional[str] = None,
    ):
        
        self.default_provider = default_provider
        self.groq_api_key = os.getenv("GROQ_API_KEY")
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        self.groq_model = groq_model or os.getenv("GROQ_MODEL", "llama3-70b-8192")
        self.openrouter_model = openrouter_model or os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet:beta")
        logger.info(Fore.CYAN + "AiClientService initialized" + Style.RESET_ALL)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        provider: Optional[Provider] = None,
        model: Optional[str] = None,
        temperature: float = 0.2,
        response_format_json: bool = True,
        timeout: float = 120.0,
    ) -> str:
        
        provider = provider or self.default_provider
        if provider == "groq":
            try :
                logger.debug(Fore.GREEN + "Preparing request for Groq..." + Style.RESET_ALL)
                return await self._groq_chat(messages, model or self.groq_model, temperature, response_format_json, timeout)
                
            except Exception as e:
                logger.debug(Fore.RED + "Error occured in calling GROQ ." + Style.RESET_ALL)
                raise HTTPException(status_code=500 , detail=f"Error occured in calling GROQ : {e}")
        
        elif provider == "openrouter":
            try :
                return await self._openrouter_chat(messages, model or self.openrouter_model, temperature, response_format_json, timeout)
            except Exception as e:
                raise f"Error occured in callint Openrouter : {e}" 
        else:
            raise ValueError("Unsupported provider")
        
    async def _groq_chat(self, messages, model, temperature, response_format_json, timeout):
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.groq_api_key}"}
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format_json:
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]

    async def _openrouter_chat(self, messages, model, temperature, response_format_json, timeout):
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "HTTP-Referer": "http://localhost",
            "X-Title": "AutoTestCases",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format_json:
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]
        

    # ---------------------------------------------------------------------------------------------
    # Testing GROQ streaming
    # async def _groq_chat_stream(self, messages, model, temperature, timeout):
    #     url = "https://api.groq.com/openai/v1/chat/completions"
    #     headers = {"Authorization": f"Bearer {self.groq_api_key}"}
    #     payload = {
    #         "model": model,
    #         "messages": messages,
    #         "temperature": temperature,
    #         "stream": True,  # enable streaming
    #     }

        # async with httpx.AsyncClient(timeout=timeout) as client:
        #     async with client.stream("POST", url, headers=headers, json=payload) as r:
        #         r.raise_for_status()
        #         async for line in r.aiter_lines():
        #             if not line.strip():
        #                 continue  # skip empty lines
        #             if line.startswith("data: "):
        #                 if line.strip() == "data: [DONE]":
        #                     break
        #                 try:
        #                     chunk = json.loads(line[len("data: "):])
        #                     delta = chunk["choices"][0]["delta"].get("content")
        #                     if delta:
        #                         yield delta
        #                 except Exception as e:
        #                     # if any malformed JSON, skip
        #                     print("Streaming parse error:", e, line)

    async def _groq_chat_stream(self, messages, model, temperature, timeout):
        try :
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {"Authorization": f"Bearer {self.groq_api_key}"}
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "stream": True,
            }

            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as r:
                    r.raise_for_status()
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        line = line.strip()
                        if line == "data: [DONE]":
                            break
                        if not line.startswith("data: "):
                            continue
                        payload_text = line[len("data: "):]
                        try:
                            chunk = json.loads(payload_text)
                        except Exception as e:
                            # malformed chunk — skip or log
                            print("Streaming parse error:", e)
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {}).get("content")
                        # yield token string (or None)
                        if delta:
                            yield delta
        except HTTPException as he:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Something went wrong {e}")

    ##Stream 
    async def stream_chat(
    self,
    messages: List[Dict[str, str]],
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.2,
    timeout: float = 120.0,
):
        try:
            """
            Yield parsed chat responses as async generator of dicts (not StreamingResponse).
            The caller can then wrap this in StreamingResponse.
            """
            provider = provider or self.default_provider
            model = model or (self.groq_model if provider == "groq" else self.openrouter_model)

            if provider == "groq":
                async def gen():
                    async for delta in self._groq_chat_stream(messages, model, temperature, timeout):
                        # Instead of yielding pre-formatted SSE, yield structured object
                        yield {"text": delta}
                return gen()  # <-- returns async generator

            elif provider == "openrouter":
                content = await self.chat(messages, provider="openrouter", model=model,
                                        temperature=temperature, timeout=timeout)

                async def gen():
                    try:
                        yield json.loads(content)
                    except Exception:
                        yield {"_raw": content}
                return gen()  # <-- returns async generator

            else:
                raise ValueError("Unsupported provider for streaming")
            
        except HTTPException as he:
            raise 
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Something went wrong in chat update : {e}")
