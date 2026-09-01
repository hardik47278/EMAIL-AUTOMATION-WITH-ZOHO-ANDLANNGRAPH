from llama_index.core import SimpleDirectoryReader
from llama_index.readers.file import PandasCSVReader


def extract_csv(file_path, max_rows=50):
    """
    CSV extractor using LlamaIndex.
    Converts CSV → LLM-ready document format.
    """

    try:
        # LlamaIndex CSV reader
        reader = PandasCSVReader()

        documents = reader.load_data(file_path)

        # LlamaIndex returns Document objects
        # We convert them into clean text chunks

        rows = []
        for doc in documents[:max_rows]:
            rows.append({
                "text": doc.text,   # main LLM-friendly content
                "metadata": doc.metadata
            })

        return {
            "type": "csv",
            "rows": rows
        }

    except Exception as e:
        return {
            "type": "csv",
            "error": str(e),
            "rows": []
        }