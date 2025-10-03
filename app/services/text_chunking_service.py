"""
smart_chunker.py
Smart text chunking with header-based and gap-based strategies
"""

import re
from typing import List, Dict


class SmartChunker:
    """
    Smart text chunker that uses multiple strategies:
    1. Header-based: Splits on numbered sections (1, 1.1, 1.2.3) or ALL CAPS headers
    2. Gap-based: Splits on paragraph breaks (2+ newlines)
    """
    
    def __init__(self, min_words: int = 40, max_words: int = 900):
        """
        Initialize SmartChunker
        
        Args:
            min_words: Minimum words per chunk (for merging small chunks)
            max_words: Maximum words per chunk (for splitting large chunks)
        """
        self.min_words = min_words
        self.max_words = max_words
        # Regex to match numbered headers (1, 1.1, 1.1.1) or ALL CAPS headers
        self.header_re = re.compile(r'(^\d+(\.\d+)*\s+.+$|^[A-Z ]{4,}$)', re.MULTILINE)
    
    def header_based(self, text: str) -> List[Dict]:
        """
        Extract chunks based on headers (numbered or ALL CAPS)
        
        Args:
            text: Input text to chunk
            
        Returns:
            List of dicts with 'section_id' and 'text' keys
        """
        matches = list(self.header_re.finditer(text))
        if not matches:
            return []
        
        chunks = []
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            section_text = text[start:end].strip()
            
            # Extract section ID from numbered headers, or generate one
            header_text = m.group(0)
            if re.match(r'^\d', header_text):
                sid = header_text.split()[0]  # Extract "1" or "1.1"
            else:
                sid = f"SEC_{i + 1:03d}"  # Generate SEC_001, SEC_002, etc.
            
            chunks.append({"section_id": sid, "text": section_text})
        
        return chunks
    
    def gap_based(self, text: str) -> List[Dict]:
        """
        Extract chunks based on paragraph gaps (2+ newlines)
        
        Args:
            text: Input text to chunk
            
        Returns:
            List of dicts with 'section_id' and 'text' keys
        """
        # Split on 2+ newlines to get paragraphs/sections
        raw_sections = [s.strip() for s in re.split(r'\n{2,}', text) if s.strip()]
        
        chunks = []
        cur = []
        cur_words = 0
        sid = 1
        
        for sec in raw_sections:
            words = sec.split()
            
            # If adding this section exceeds max_words, save current chunk
            if cur_words + len(words) > self.max_words:
                if cur:
                    chunks.append({
                        "section_id": f"SEC_{sid:03d}",
                        "text": " ".join(cur).strip()
                    })
                    sid += 1
                cur = words
                cur_words = len(words)
            else:
                cur.extend(words)
                cur_words += len(words)
        
        # Add remaining content
        if cur:
            chunks.append({
                "section_id": f"SEC_{sid:03d}",
                "text": " ".join(cur).strip()
            })
        
        # Merge chunks that are too small with their neighbors
        merged = []
        for c in chunks:
            word_count = len(c["text"].split())
            if not merged or len(merged[-1]["text"].split()) >= self.min_words:
                merged.append(c)
            else:
                # Merge with previous chunk
                merged[-1]["text"] += " " + c["text"]
        
        return merged
    
    def chunk(self, text: str) -> List[Dict]:
        """
        Main chunking method - automatically selects best strategy
        
        Tries header-based first, falls back to gap-based if no headers found.
        Also splits any oversized chunks.
        
        Args:
            text: Input text to chunk
            
        Returns:
            List of dicts with 'section_id' and 'text' keys
        """
        # Try header-based chunking first
        chunks = self.header_based(text)
        
        if chunks:
            # Split any chunks that are still too large
            out = []
            for ch in chunks:
                if len(ch["text"].split()) > self.max_words:
                    out.extend(self._split_by_paragraphs(ch))
                else:
                    out.append(ch)
            return out
        
        # Fall back to gap-based chunking
        return self.gap_based(text)
    
    def _split_by_paragraphs(self, chunk: Dict) -> List[Dict]:
        """
        Split an oversized chunk by paragraphs
        
        Args:
            chunk: Dict with 'section_id' and 'text'
            
        Returns:
            List of smaller chunks
        """
        paras = [p.strip() for p in chunk["text"].split("\n\n") if p.strip()]
        
        out = []
        cur = []
        cur_words = 0
        sid = 1
        
        for p in paras:
            w = p.split()
            
            if cur_words + len(w) > self.max_words:
                if cur:
                    out.append({
                        "section_id": f"{chunk['section_id']}_{sid}",
                        "text": " ".join(cur)
                    })
                    sid += 1
                cur = w
                cur_words = len(w)
            else:
                cur.extend(w)
                cur_words += len(w)
        
        if cur:
            out.append({
                "section_id": f"{chunk['section_id']}_{sid}",
                "text": " ".join(cur)
            })
        
        return out