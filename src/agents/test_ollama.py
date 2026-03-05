import ollama

response = ollama.chat(
    model="mistral:7b",
    messages=[
        {
            "role": "user",
            "content": "You are a Kentucky Wildcats basketball analyst. Write one exciting sentence about UK Basketball being 19-11 and ranked 8th in the SEC."
        }
    ]
)

print(response["message"]["content"])