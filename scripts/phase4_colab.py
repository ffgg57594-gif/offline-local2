# Phase 4: LoRA fine-tune on Colab (Unsloth). Run on Colab (free GPU).
# !pip install unsloth transformers trl datasets accelerate bitsandbytes
import json
from datasets import Dataset
from unsloth import FastLanguageModel
from trl import SFTTrainer
from transformers import TrainingArguments

MODEL = "unsloth/Qwen2.5-0.5B-Instruct-bnb-4bit"  # or 1.5B
MAX_SEQ = 1024

# Load data
rows = [json.loads(l) for l in open("ft_data.jsonl", encoding="utf-8")]
def fmt(e):
    return f"<|im_start|>user\n{e['instruction']}\n\n{e['input']}<|im_end|>\n<|im_start|>assistant\n{e['output']}<|im_end|>"
ds = Dataset.from_list([{"text": fmt(e)} for e in rows])
split = ds.train_test_split(test_size=0.2, seed=42)
train_ds, eval_ds = split["train"], split["test"]

model, tok = FastLanguageModel.from_pretrained(MODEL, max_seq_length=MAX_SEQ, load_in_4bit=True)
model = FastLanguageModel.get_peft_model(model, r=16, target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"], lora_alpha=32, lora_dropout=0.05, bias="none", use_gradient_checkpointing="unsloth")

trainer = SFTTrainer(model=model, tokenizer=tok, train_dataset=train_ds, eval_dataset=eval_ds,
    dataset_text_field="text", max_seq_length=MAX_SEQ, packing=True,
    args=TrainingArguments(output_dir="lora_out", num_train_epochs=3, per_device_train_batch_size=4,
        gradient_accumulation_steps=4, learning_rate=2e-4, fp16=True, logging_steps=10,
        eval_strategy="steps", eval_steps=50, save_steps=100, optim="adamw_8bit"))
trainer.train()
model.save_pretrained("lora_out")
tok.save_pretrained("lora_out")
print("LoRA saved to lora_out/")

# Eval: refusal accuracy + verifier pass (run after)
# - refusal accuracy: % of held-out refusal examples predicted as refusal
# - verifier pass: % of quoted spans found verbatim in retrieved paragraphs
print("Next: Phase 5 verifier + export (GGUF Q4 + ONNX int8)")
