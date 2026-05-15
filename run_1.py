from vertexai.generative_models import GenerationConfig, GenerativeModel
from dotenv import load_dotenv
import vertexai
import os

def get_env_var(name: str, required: bool = True) -> str:
    value = os.getenv(name)
    if required and not value:
        raise
    return value

def main():
    load_dotenv()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = f"{os.getcwd()}\\credentials.json"

    vertexai.init(project = get_env_var("PROJECT_ID"), location = get_env_var("LOCATION"))

    model = GenerativeModel(
        get_env_var("MODEL_NAME"),
        generation_config = GenerationConfig(temperature = 0.0, top_p = 0.95, top_k = 20)
    )

    csv_path = r"C:\Users\mnstsalg\Documents\03_posh_tests_ai\products.csv"

    with open(csv_path, "r", encoding = "utf-8") as f:
        csv_content = f.read()

    model_to_search = "MOTOROLA MOTO G06 4G 128GB-AZUL MARINHO"
    
    costumer = "Cidade: sao paulo Estado:SP"
    
    prompt = f"""

    Você é um assistente especializado em busca de produtos em bases de dados.
    
    Busque o seguinte modelo no banco de dados abaixo: {model_to_search}
    
    Considere variações de escrita, abreviações, ordem das palavras e pequenas diferenças de formatação.
    Se não encontrar correspondência exata, retorne o produto mais próximo.

    Retorne APENAS os dados do produto encontrado, um campo por linha, no formato:
    NOME_DA_COLUNA: valor

    Nenhum texto adicional, sem explicações, sem cabeçalho.
    
    Obedeça as seguintes regras de negócio:
    Regra de negócio:
        1. se o Customer for de SP o produto é de JAG, caso contrário, o Customer não for de SP o produto é de MAN

    costumer: {costumer} -
    Base de dados:
    {csv_content}
    """

    response = model.generate_content([prompt])

    print(response.text)

if __name__ == "__main__":
    main()