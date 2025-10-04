"""
vector_store_service.py
Service for managing document embeddings with ChromaDB and LangChain
"""

import os
from typing import List, Dict, Optional
from pathlib import Path

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document

from logs.logger_config import get_logger
from colorama import Fore, Style

logger = get_logger("VectorStoreService")


class VectorStoreService:
    """
    Manages document embeddings and vector storage using ChromaDB
    Integrates with SmartChunker output for content-aware retrieval
    """
    
    def __init__(
        self,
        persist_directory: str = "chroma_data",
        embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    ):
        """
        Initialize VectorStoreService
        
        Args:
            persist_directory: Directory to persist ChromaDB data
            embedding_model_name: HuggingFace model for embeddings (free, local)
        """
        self.persist_directory = persist_directory
        Path(persist_directory).mkdir(parents=True, exist_ok=True)
        
        # Use free, local embeddings (no API key needed)
        self.embedding_function = HuggingFaceEmbeddings(
            model_name=embedding_model_name,
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': True}
        )
        
        logger.info(
            Fore.CYAN + 
            f"VectorStoreService initialized with {embedding_model_name}" + 
            Style.RESET_ALL
        )
    
    async def ingest_document_chunks(
        self,
        document_id: int,
        project_id: int,
        chunks: List[Dict],
        doctype: str,
        collection_name: Optional[str] = None
    ) -> Dict:
        """
        Ingest document chunks into ChromaDB
        
        Args:
            document_id: Document ID
            project_id: Project ID
            chunks: List of chunks from SmartChunker (with section_id and text)
            doctype: Document type (BRD, SRS, etc.)
            collection_name: Optional collection name (defaults to project_id)
            
        Returns:
            Dict with ingestion status and stats
        """
        try:
            collection_name = collection_name or f"project_{project_id}"
            
            # Convert chunks to LangChain Documents with metadata
            documents = []
            for idx, chunk in enumerate(chunks):
                doc = Document(
                    page_content=chunk["text"],
                    metadata={
                        "document_id": document_id,
                        "project_id": project_id,
                        "section_id": chunk["section_id"],
                        "doctype": doctype,
                        "chunk_index": idx,
                        "chunk_length": len(chunk["text"])
                    }
                )
                documents.append(doc)
            
            logger.debug(
                Fore.GREEN + 
                f"Prepared {len(documents)} documents for ingestion" + 
                Style.RESET_ALL
            )
            
            # Create or load ChromaDB collection
            vectorstore = Chroma(
                collection_name=collection_name,
                embedding_function=self.embedding_function,
                persist_directory=self.persist_directory
            )
            
            # Add documents to vectorstore
            ids = vectorstore.add_documents(documents)
            
            logger.info(
                Fore.GREEN + 
                f"Ingested {len(ids)} chunks for doc_{document_id} into {collection_name}" + 
                Style.RESET_ALL
            )
            
            return {
                "status": "success",
                "document_id": document_id,
                "project_id": project_id,
                "collection_name": collection_name,
                "chunks_ingested": len(ids),
                "vector_ids": ids
            }
            
        except Exception as e:
            logger.error(
                Fore.RED + 
                f"Error ingesting document chunks: {str(e)}" + 
                Style.RESET_ALL
            )
            raise Exception(f"Vector ingestion failed: {str(e)}")
    
    async def search_similar_chunks(
        self,
        query: str,
        project_id: int,
        k: int = 5,
        filter_metadata: Optional[Dict] = None,
        collection_name: Optional[str] = None
    ) -> List[Dict]:
        """
        Search for similar chunks using semantic similarity
        
        Args:
            query: Search query text
            project_id: Project ID to search within
            k: Number of results to return
            filter_metadata: Optional metadata filters (e.g., {"doctype": "BRD"})
            collection_name: Optional collection name
            
        Returns:
            List of matching chunks with metadata and similarity scores
        """
        try:
            collection_name = collection_name or f"project_{project_id}"
            
            vectorstore = Chroma(
                collection_name=collection_name,
                embedding_function=self.embedding_function,
                persist_directory=self.persist_directory
            )
            
            # Build filter for project_id and any additional filters
            where_filter = {"project_id": project_id}
            if filter_metadata:
                where_filter.update(filter_metadata)
            
            # Perform similarity search
            results = vectorstore.similarity_search_with_score(
                query=query,
                k=k,
                filter=where_filter
            )
            
            # Format results
            formatted_results = []
            for doc, score in results:
                formatted_results.append({
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                    "similarity_score": float(score)
                })
            
            logger.debug(
                Fore.CYAN + 
                f"Found {len(formatted_results)} similar chunks for query" + 
                Style.RESET_ALL
            )
            
            return formatted_results
            
        except Exception as e:
            logger.error(
                Fore.RED + 
                f"Error searching similar chunks: {str(e)}" + 
                Style.RESET_ALL
            )
            raise Exception(f"Vector search failed: {str(e)}")
    
    async def get_context_for_query(
        self,
        query: str,
        project_id: int,
        max_chunks: int = 3,
        doctype: Optional[str] = None
    ) -> str:
        """
        Get relevant context from documents for a query
        Useful for RAG (Retrieval Augmented Generation)
        
        Args:
            query: User query
            project_id: Project ID
            max_chunks: Maximum chunks to include in context
            doctype: Optional document type filter
            
        Returns:
            Formatted context string for LLM
        """
        filter_metadata = {"doctype": doctype} if doctype else None
        
        results = await self.search_similar_chunks(
            query=query,
            project_id=project_id,
            k=max_chunks,
            filter_metadata=filter_metadata
        )
        
        if not results:
            return "No relevant context found."
        
        # Build context string
        context_parts = []
        for idx, result in enumerate(results, 1):
            meta = result["metadata"]
            context_parts.append(
                f"[Context {idx} - {meta['doctype']} - Section {meta['section_id']}]\n"
                f"{result['content']}\n"
            )
        
        return "\n".join(context_parts)
    
    async def delete_document_chunks(
        self,
        document_id: int,
        project_id: int,
        collection_name: Optional[str] = None
    ) -> Dict:
        """
        Delete all chunks for a specific document
        
        Args:
            document_id: Document ID to delete
            project_id: Project ID
            collection_name: Optional collection name
            
        Returns:
            Deletion status
        """
        try:
            collection_name = collection_name or f"project_{project_id}"
            
            vectorstore = Chroma(
                collection_name=collection_name,
                embedding_function=self.embedding_function,
                persist_directory=self.persist_directory
            )
            
            # Get all IDs for this document
            results = vectorstore.get(
                where={"document_id": document_id, "project_id": project_id}
            )
            
            if results and results['ids']:
                vectorstore.delete(ids=results['ids'])
                logger.info(
                    Fore.YELLOW + 
                    f"Deleted {len(results['ids'])} chunks for doc_{document_id}" + 
                    Style.RESET_ALL
                )
                return {
                    "status": "success",
                    "deleted_chunks": len(results['ids'])
                }
            
            return {
                "status": "success",
                "deleted_chunks": 0,
                "message": "No chunks found for document"
            }
            
        except Exception as e:
            logger.error(
                Fore.RED + 
                f"Error deleting document chunks: {str(e)}" + 
                Style.RESET_ALL
            )
            raise Exception(f"Vector deletion failed: {str(e)}")