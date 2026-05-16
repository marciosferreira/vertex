import os
import io
import sys
import json
import textwrap
import traceback
import uuid
from datetime import datetime
from typing import Dict, Any, List
from mcp.types import TextContent
import pandas as pd
import numpy as np
import math

# --- CORREÇÃO DE AMBIENTE WINDOWS (MCP/SANDBOX) ---
# Garante que o Matplotlib encontre as fontes do sistema no Windows

# --- CARREGAMENTO RESILIENTE DO MATPLOTLIB ---
HAS_MATPLOTLIB = False
MATPLOTLIB_ERROR = None

try:
    import matplotlib
    # Força o backend não-interativo antes de importar o pyplot
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except Exception as e:
    plt = None
    HAS_MATPLOTLIB = False
    MATPLOTLIB_ERROR = f"{type(e).__name__}: {str(e)}"

async def query_pandas_dataframe(arguments: Dict[str, Any]):
    """
    Executa código Pandas com isolamento de ambiente e captura de gráficos.
    """
    # 1. Extração de Argumentos
    user_id = arguments.get("user_id")
    cache_id = arguments.get("cache_id")
    user_data_cache = arguments.get("user_data_cache", {})
    pandas_code = arguments.get("pandas_code", "").strip()
    output_format = (arguments.get("output_format") or "markdown").strip().lower()
    max_rows_raw = arguments.get("max_rows", 50)

    try:
        max_rows = int(max_rows_raw) if max_rows_raw is not None else 50
    except Exception:
        max_rows = 50

    if user_id is None:
        return [TextContent(type="text", text=f"Erro: user_id não informado.")]

    safe_user_id = str(user_id)
    if safe_user_id in user_data_cache:
        user_cache = user_data_cache[safe_user_id]
    elif user_id in user_data_cache:
        user_cache = user_data_cache[user_id]
    else:
        return [TextContent(type="text", text=f"Erro: Usuário {user_id} não possui dados em cache.")]

    # 2. Seleção e Aliasing do DataFrame
    dataframes_dict = {}
    df_principal = None
    
    is_ota_context = "ota" in str(cache_id).lower() if cache_id else False

    def _extract_named_dataframes(cache_entry: Any) -> Dict[str, pd.DataFrame]:
        if not isinstance(cache_entry, dict):
            return {}
        if isinstance(cache_entry.get("data"), dict):
            base = cache_entry["data"]
        elif isinstance(cache_entry.get("ota_dataframes"), dict):
            base = cache_entry["ota_dataframes"]
        else:
            return {}
        out: Dict[str, pd.DataFrame] = {}
        for name, val in base.items():
            if isinstance(val, pd.DataFrame):
                out[str(name)] = val
        return out

    cache_bucket = user_cache.get(str(cache_id)) if cache_id is not None else None
    if isinstance(cache_bucket, list) and cache_bucket:
        named_dfs = _extract_named_dataframes(cache_bucket[-1])
        if named_dfs:
            dataframes_dict.update(named_dfs)
            if isinstance(named_dfs.get("df"), pd.DataFrame):
                df_principal = named_dfs["df"]
            elif isinstance(named_dfs.get("productPeriods"), pd.DataFrame):
                df_principal = named_dfs["productPeriods"]
            else:
                df_principal = next(iter(named_dfs.values()), None)

    if df_principal is None:
        if isinstance(user_cache.get("df"), pd.DataFrame):
            df_principal = user_cache["df"]
        else:
            for k, v in user_cache.items():
                if isinstance(v, pd.DataFrame):
                    df_principal = v
                    break

    if df_principal is None:
        keys_preview = ", ".join(list(user_cache.keys())[:30])
        return [TextContent(type="text", text=f"Erro: Nenhum DataFrame encontrado no cache. Keys: {keys_preview}")]

    dataframes_dict.setdefault("df", df_principal)
    if is_ota_context and "productPeriods" not in dataframes_dict:
        if isinstance(user_cache.get("productPeriods"), pd.DataFrame):
            dataframes_dict["productPeriods"] = user_cache["productPeriods"]
        else:
            dataframes_dict["productPeriods"] = df_principal

    # --- VERIFICAÇÃO DE DEPENDÊNCIA ---
    if ("plt" in pandas_code or "matplotlib" in pandas_code) and not HAS_MATPLOTLIB:
        return [TextContent(type="text", text=f"ERRO DE AMBIENTE: Matplotlib indisponível.\nDetalhes: {MATPLOTLIB_ERROR}")]

    # 3. Preparação do Ambiente de Execução (Sandbox)
    global_vars_key = f"global_vars_environment_{user_id}"
    exec_globals = {
        "pd": pd, 
        "np": np, 
        "os": os, # Mantido para caminhos, mas cuidado com segurança
        "datetime": datetime,
        **dataframes_dict
    }

    if global_vars_key in user_cache:
        saved_vars = user_cache[global_vars_key]
        for var_name, var_value in saved_vars.items():
            if var_name not in ["df", "result", "productPeriods"]:
                exec_globals[var_name] = var_value

    # 4. Captura de Saída e Redirecionamento de Gráficos
    old_stdout = sys.stdout
    mystdout = io.StringIO()
    sys.stdout = mystdout
    
    generated_images = []
    original_show = None

    if HAS_MATPLOTLIB:
        # Configurações de UX para os gráficos gerados pela IA
        plt.rcParams.update({
            'figure.figsize': [12, 7],
            'figure.dpi': 140,
            'axes.titlesize': 14,
            'savefig.bbox': 'tight'
        })
        
        original_show = plt.show

        def custom_show():
            """Sobrescreve plt.show() para salvar em disco em vez de abrir janela."""
            fignums = plt.get_fignums()
            if not fignums:
                return
                
            save_dir = os.path.join(os.getcwd(), "static", "images")
            os.makedirs(save_dir, exist_ok=True)
            
            # Preparar construtor de URL respeitando ROOT_PATH/PUBLIC_BASE_URL
            base_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
            root_path_env = os.getenv("FASTAPI_ROOT_PATH", os.getenv("ROOT_PATH", "")).strip("/")

            def _image_url(name: str) -> str:
                path = f"/static/images/{name}"
                if root_path_env:
                    path = f"/{root_path_env}{path}"
                return f"{base_url}{path}" if base_url else path

            for fignum in fignums:
                fig = plt.figure(fignum)
                try:
                    for ax in fig.axes:
                        xticks = ax.get_xticklabels()
                        n = len(xticks)
                        if n > 12:
                            step = max(1, int(math.ceil(n / 12)))
                            for i, lab in enumerate(xticks):
                                lab.set_visible((i % step) == 0)
                            for lab in ax.get_xticklabels():
                                lab.set_rotation(45)
                                lab.set_ha('right')
                            fig.subplots_adjust(bottom=0.22)
                        try:
                            ax.autoscale(enable=True, axis='both', tight=False)
                            ax.margins(x=0.12, y=0.12)
                            leg = ax.get_legend()
                            if leg is not None:
                                ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1), borderaxespad=0, frameon=True)
                        except Exception:
                            pass
                except Exception:
                    pass
                filename = f"graph_{uuid.uuid4().hex[:12]}.png"
                filepath = os.path.join(save_dir, filename)
                plt.savefig(filepath, format='png')
                generated_images.append(_image_url(filename))
                plt.close(fignum)

        plt.show = custom_show
        exec_globals['plt'] = plt

    try:
        # 5. Execução do Código
        code_to_run = textwrap.dedent(pandas_code).lstrip("\n")
        exec(code_to_run, exec_globals)
        
        console_output = mystdout.getvalue().strip()
        result_var = exec_globals.get("result")
        
        # 6. Formatação da Resposta
        if output_format not in {"markdown", "csv", "json"}:
            output_format = "markdown"

        if output_format == "csv":
            res_text = _format_result_csv(result_var, console_output, max_rows)
        elif output_format == "json":
            res_text = _format_result_json(result_var, console_output, generated_images, max_rows)
        else:
            if console_output:
                res_text = f"Saída do console:\n```\n{console_output}\n```"
            elif result_var is not None:
                output_data = _format_result_output(result_var, "", max_rows)
                res_text = output_data[0].text if hasattr(output_data[0], 'text') else str(output_data[0])
            else:
                res_text = "Análise concluída com sucesso."

            if generated_images:
                res_text += "\n\n### Gráficos Gerados:"
                for img_url in generated_images:
                    res_text += f"\n\n![Gráfico]({img_url})"

        # 7. Persistência de Variáveis (Ignora objetos pesados ou callables)
        new_saved_vars = {
            k: v for k, v in exec_globals.items() 
            if not k.startswith("__") 
            and not callable(v) 
            and k not in ["pd", "np", "df", "plt", "productPeriods", "os", "datetime"]
        }
        user_cache[global_vars_key] = new_saved_vars
        
        vars_info = _generate_variables_info_compact(exec_globals)
        if output_format in {"csv", "json"}:
            return [TextContent(type="text", text=res_text)]
        return [TextContent(type="text", text=f"{res_text}\n\n{vars_info}")]

    except Exception as e:
        extra = ""
        if isinstance(e, KeyError) and df_principal is not None:
            try:
                cols = [str(c) for c in df_principal.columns]
                preview = ", ".join(cols[:80])
                suffix = "..." if len(cols) > 80 else ""
                extra = f"\n\nColunas disponíveis no DataFrame (df):\n{preview}{suffix}\n\nDica: rode `print(df.columns.tolist())` e ajuste os nomes das colunas no código."
            except Exception:
                extra = ""
        error_msg = f"Erro na execução do código:\n{type(e).__name__}: {str(e)}{extra}\n\n{traceback.format_exc()}"
        return [TextContent(type="text", text=error_msg)]
    
    finally:
        # Restaura o estado original do sistema
        sys.stdout = old_stdout
        if HAS_MATPLOTLIB:
            plt.close('all') # Garante que nada ficou aberto
            if original_show:
                plt.show = original_show

# --- Auxiliares ---
def _generate_variables_info_compact(exec_globals):
    vars_list = [f"{k} ({type(v).__name__})" for k, v in exec_globals.items() 
                 if not k.startswith("_") and k not in ["pd", "np", "datetime", "plt", "os"]]
    return "💡 **Contexto atual:** " + ", ".join(vars_list) if vars_list else ""

def _format_result_output(result, q, max_rows: int = 50):
    if isinstance(result, pd.DataFrame):
        df = result
        if max_rows > 0:
            df = df.head(max_rows)
        return [TextContent(type="text", text=df.to_markdown())]
    if isinstance(result, pd.Series):
        s = result
        if max_rows > 0:
            s = s.head(max_rows)
        return [TextContent(type="text", text=s.to_frame().to_markdown())]
    return [TextContent(type="text", text=str(result))]


def _format_result_csv(result_var, console_output: str, max_rows: int) -> str:
    if isinstance(result_var, pd.DataFrame):
        df = result_var
        if max_rows > 0:
            df = df.head(max_rows)
        return df.to_csv(index=False)
    if isinstance(result_var, pd.Series):
        s = result_var
        if max_rows > 0:
            s = s.head(max_rows)
        return s.to_frame().reset_index().to_csv(index=False)
    if console_output:
        return console_output
    if result_var is None:
        return ""
    return str(result_var)


def _format_result_json(result_var, console_output: str, generated_images: List[str], max_rows: int) -> str:
    payload: Dict[str, Any] = {"images": generated_images}
    if console_output:
        payload["console"] = console_output

    if isinstance(result_var, pd.DataFrame):
        df = result_var
        if max_rows > 0:
            df = df.head(max_rows)
        payload["result_type"] = "dataframe"
        payload["result"] = df.to_dict(orient="records")
        payload["columns"] = list(df.columns)
    elif isinstance(result_var, pd.Series):
        s = result_var
        if max_rows > 0:
            s = s.head(max_rows)
        payload["result_type"] = "series"
        payload["result"] = s.to_dict()
    else:
        payload["result_type"] = type(result_var).__name__ if result_var is not None else "none"
        payload["result"] = result_var

    try:
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return json.dumps({"result": str(payload)}, ensure_ascii=False)