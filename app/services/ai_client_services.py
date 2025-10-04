"""
enhanced_ai_client_service.py
AI Client Service with integrated vector store for context-aware generation
"""

from fastapi import HTTPException
import json
import os
import httpx
from typing import List, Literal, Optional, Dict, Any
from pathlib import Path

from logs.logger_config import get_logger
from colorama import Fore, Style

logger = get_logger("AiClientService")

Provider = Literal["groq", "openrouter"]


class AiClientService:
    """
    Enhanced AI Client with vector store integration for context awareness
    Maintains semantic memory across chunk-based processing
    """
    
    def __init__(
        self,
        default_provider: Provider = "groq",
        groq_model: Optional[str] = None,
        openrouter_model: Optional[str] = None,
        vector_service = None  # VectorStoreService instance
    ):
        self.default_provider = default_provider
        self.groq_api_key = os.getenv("GROQ_API_KEY")
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        self.groq_model = groq_model or os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        self.openrouter_model = openrouter_model or os.getenv(
            "OPENROUTER_MODEL", 
            "anthropic/claude-3.5-sonnet:beta"
        )
        
        # Vector store integration (lazy loaded)
        self._vector_service = vector_service
        
        logger.info(
            Fore.CYAN + 
            "EnhancedAiClientService initialized with vector support" + 
            Style.RESET_ALL
        )
    
    @property
    def vector_service(self):
        """Lazy load vector service to avoid circular imports"""
        if self._vector_service is None:
            from app.services.vector_store_service import VectorStoreService
            self._vector_service = VectorStoreService()
        return self._vector_service
    
    # =========================================================================
    # Core Chat Methods (unchanged)
    # =========================================================================
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        provider: Optional[Provider] = None,
        model: Optional[str] = None,
        temperature: float = 0.2,
        response_format_json: bool = True,
        timeout: float = 120.0,
    ) -> str:
        """Standard chat without context retrieval"""
        provider = provider or self.default_provider
        
        if provider == "groq":
            try:
                logger.debug(Fore.GREEN + "Preparing request for Groq..." + Style.RESET_ALL)
                return await self._groq_chat(
                    messages, 
                    model or self.groq_model, 
                    temperature, 
                    response_format_json, 
                    timeout
                )
            except Exception as e:
                logger.error(Fore.RED + f"Error calling GROQ: {e}" + Style.RESET_ALL)
                raise HTTPException(
                    status_code=500, 
                    detail=f"Error calling GROQ: {e}"
                )
        
        elif provider == "openrouter":
            try:
                return await self._openrouter_chat(
                    messages, 
                    model or self.openrouter_model, 
                    temperature, 
                    response_format_json, 
                    timeout
                )
            except Exception as e:
                raise HTTPException(
                    status_code=500, 
                    detail=f"Error calling OpenRouter: {e}"
                )
        else:
            raise ValueError("Unsupported provider")
    
    async def _groq_chat(
        self, 
        messages, 
        model, 
        temperature, 
        response_format_json, 
        timeout
    ):
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
    
    async def _openrouter_chat(
        self, 
        messages, 
        model, 
        temperature, 
        response_format_json, 
        timeout
    ):
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
    
    # =========================================================================
    # Context-Aware Chat Methods (NEW)
    # =========================================================================
    
    async def chat_with_context(
        self,
        messages: List[Dict[str, str]],
        project_id: int,
        document_id: Optional[int] = None,
        max_context_chunks: int = 3,
        doctype: Optional[str] = None,
        provider: Optional[Provider] = None,
        model: Optional[str] = None,
        temperature: float = 0.2,
        response_format_json: bool = True,
        timeout: float = 120.0,
    ) -> Dict[str, Any]:
        """
        Chat with automatic context retrieval from vector store
        
        Args:
            messages: Chat messages (last user message used for retrieval)
            project_id: Project ID for context search
            document_id: Optional document filter
            max_context_chunks: Max chunks to retrieve
            doctype: Optional document type filter
            ... (other standard chat params)
            
        Returns:
            Dict with response, retrieved_context, and sources
        """
        try:
            # Extract query from last user message
            user_messages = [m for m in messages if m.get("role") == "user"]
            if not user_messages:
                raise ValueError("No user message found for context retrieval")
            
            query = user_messages[-1].get("content", "")
            
            # Retrieve relevant context
            logger.debug(
                Fore.CYAN + 
                f"Retrieving context for: '{query[:50]}...'" + 
                Style.RESET_ALL
            )
            
            filter_metadata = {}
            if doctype:
                filter_metadata["doctype"] = doctype
            if document_id:
                filter_metadata["document_id"] = document_id
            
            search_results = await self.vector_service.search_similar_chunks(
                query=query,
                project_id=project_id,
                k=max_context_chunks,
                filter_metadata=filter_metadata if filter_metadata else None
            )
            
            # Build context string
            context_parts = []
            for idx, result in enumerate(search_results, 1):
                meta = result["metadata"]
                context_parts.append(
                    f"[Context {idx} - Doc {meta['document_id']} - "
                    f"{meta['doctype']} - Section {meta['section_id']}]\n"
                    f"{result['content']}\n"
                )
            
            context = "\n".join(context_parts) if context_parts else "No relevant context found."
            
            # Inject context into system message or create new one
            enhanced_messages = self._inject_context(messages, context)
            
            # Make chat call
            logger.debug(Fore.GREEN + "Calling LLM with enhanced context..." + Style.RESET_ALL)
            response = await self.chat(
                messages=enhanced_messages,
                provider=provider,
                model=model,
                temperature=temperature,
                response_format_json=response_format_json,
                timeout=timeout
            )
            
            return {
                "response": response,
                "retrieved_context": context,
                "context_chunks_used": len(search_results),
                "sources": [
                    {
                        "document_id": r["metadata"]["document_id"],
                        "section_id": r["metadata"]["section_id"],
                        "doctype": r["metadata"]["doctype"],
                        "similarity_score": r["similarity_score"]
                    }
                    for r in search_results
                ]
            }
            
        except Exception as e:
            logger.error(
                Fore.RED + 
                f"Context-aware chat failed: {e}" + 
                Style.RESET_ALL
            )
            raise HTTPException(
                status_code=500,
                detail=f"Context-aware chat failed: {e}"
            )
    
    def _inject_context(
        self, 
        messages: List[Dict[str, str]], 
        context: str
    ) -> List[Dict[str, str]]:
        """
        Inject retrieved context into messages
        
        Strategy: Add context to system message or create one
        """
        enhanced = messages.copy()
        
        context_instruction = (
            f"\n\nRELEVANT CONTEXT FROM DOCUMENTS:\n{context}\n\n"
            "Use this context to inform your response. "
            "Reference specific sections when applicable."
        )
        
        # If system message exists, append context
        if enhanced and enhanced[0].get("role") == "system":
            enhanced[0]["content"] += context_instruction
        else:
            # Create new system message with context
            enhanced.insert(0, {
                "role": "system",
                "content": (
                    "You are a helpful assistant with access to relevant document context."
                    + context_instruction
                )
            })
        
        return enhanced
    
    # =========================================================================
    # Chunk-Aware Generation (for TestCase Generation)
    # =========================================================================
    
    async def generate_with_chunk_context(
        self,
        current_chunk: Dict[str, str],
        project_id: int,
        document_id: int,
        generation_prompt: str,
        max_related_chunks: int = 2,
        provider: Optional[Provider] = None,
        model: Optional[str] = None,
        temperature: float = 0.2,
        response_format_json: bool = True,
        timeout: float = 120.0,
    ) -> Dict[str, Any]:
        """
        Generate content for a chunk with awareness of related chunks
        
        Perfect for test case generation where each chunk needs context
        from related sections
        
        Args:
            current_chunk: Current chunk being processed
            project_id: Project ID
            document_id: Document ID
            generation_prompt: Task prompt (e.g., "Generate test cases")
            max_related_chunks: Max related chunks to retrieve
            ... (other params)
            
        Returns:
            Dict with generated content and context info
        """
        try:
            chunk_text = current_chunk.get("text", "")
            chunk_id = current_chunk.get("section_id", "unknown")
            
            # Retrieve related chunks (excluding current one)
            logger.debug(
                Fore.CYAN + 
                f"Retrieving context for chunk {chunk_id}..." + 
                Style.RESET_ALL
            )
            
            search_results = await self.vector_service.search_similar_chunks(
                query=chunk_text,
                project_id=project_id,
                k=max_related_chunks + 1,  # +1 because current chunk might appear
                filter_metadata={"document_id": document_id}
            )
            
            # Filter out current chunk
            related_chunks = [
                r for r in search_results 
                if r["metadata"]["section_id"] != chunk_id
            ][:max_related_chunks]
            
            # Build context from related chunks
            related_context = ""
            if related_chunks:
                context_parts = []
                for r in related_chunks:
                    meta = r["metadata"]
                    context_parts.append(
                        f"[Related Section {meta['section_id']}]\n{r['content']}\n"
                    )
                related_context = (
                    "\n\nRELATED SECTIONS FOR CONTEXT:\n" + 
                    "\n".join(context_parts)
                )
            
            # Build messages
            system_msg = {
                "role": "system",
                "content": (
                    f"You are processing a requirement document chunk by chunk. "
                    f"Consider related sections for context consistency. "
                    f"Output strictly valid JSON."
                )
            }
            
            user_msg = {
                "role": "user",
                "content": (
                    f"{generation_prompt}\n\n"
                    f"CURRENT CHUNK [ID: {chunk_id}]:\n{chunk_text}"
                    f"{related_context}"
                )
            }
            
            # Generate
            logger.debug(
                Fore.GREEN + 
                f"Generating for chunk {chunk_id} with {len(related_chunks)} related chunks..." + 
                Style.RESET_ALL
            )
            
            response = await self.chat(
                messages=[system_msg, user_msg],
                provider=provider,
                model=model,
                temperature=temperature,
                response_format_json=response_format_json,
                timeout=timeout
            )
            
            return {
                "chunk_id": chunk_id,
                "response": response,
                "related_chunks_used": len(related_chunks),
                "related_sources": [
                    {
                        "section_id": r["metadata"]["section_id"],
                        "similarity_score": r["similarity_score"]
                    }
                    for r in related_chunks
                ]
            }
            
        except Exception as e:
            logger.error(
                Fore.RED + 
                f"Chunk-aware generation failed: {e}" + 
                Style.RESET_ALL
            )
            raise HTTPException(
                status_code=500,
                detail=f"Chunk-aware generation failed: {e}"
            )
    
    # =========================================================================
    # Streaming (unchanged, for completeness)
    # =========================================================================
    
    async def _groq_chat_stream(self, messages, model, temperature, timeout):
        try:
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
                            print("Streaming parse error:", e)
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {}).get("content")
                        if delta:
                            yield delta
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500, 
                detail=f"Streaming failed: {e}"
            )

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.2,
        timeout: float = 120.0,
    ):
        try:
            provider = provider or self.default_provider
            model = model or (
                self.groq_model if provider == "groq" else self.openrouter_model
            )

            if provider == "groq":
                async def gen():
                    async for delta in self._groq_chat_stream(
                        messages, model, temperature, timeout
                    ):
                        yield {"text": delta}
                return gen()

            elif provider == "openrouter":
                content = await self.chat(
                    messages, 
                    provider="openrouter", 
                    model=model,
                    temperature=temperature, 
                    timeout=timeout
                )

                async def gen():
                    try:
                        yield json.loads(content)
                    except Exception:
                        yield {"_raw": content}
                return gen()

            else:
                raise ValueError("Unsupported provider for streaming")
            
        except HTTPException:
            raise 
        except Exception as e:
            raise HTTPException(
                status_code=500, 
                detail=f"Stream chat failed: {e}"
            )