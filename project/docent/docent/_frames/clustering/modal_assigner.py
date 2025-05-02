import modal
import torch
from transformers import ModernBertForSequenceClassification

# Create Modal stub and configure image
app = modal.App("cluster-assigner")

# Custom image with required dependencies
image = modal.Image.debian_slim().pip_install(
    "torch==2.5.1",
    "transformers==4.48.3",
)

# Create Modal volume to persist model weights
model_volume = modal.Volume.from_name("cluster-assigner-031825")


@app.cls(
    image=image,
    gpu="A10G",
    volumes={"/model": model_volume},
    keep_warm=1,
    concurrency_limit=10,
    allow_concurrent_inputs=10,
)
class ModalClusterAssigner:
    @modal.enter()
    def __enter__(self):
        self.device = "cuda"
        self.model = ModernBertForSequenceClassification.from_pretrained("/model/checkpoint-231")
        self.model.to(torch.bfloat16).to(self.device)
        self.model.eval()

    @modal.method()
    def assign(self, encoded_inputs) -> list[tuple[bool, str] | None]:
        encoded_inputs.to(self.device)
        with torch.no_grad():
            outputs = self.model(**encoded_inputs)
            logits = outputs.logits
            batch_probs = torch.softmax(logits, dim=1)
            batch_predictions = torch.argmax(logits, dim=1)

        return batch_predictions.cpu(), batch_probs.cpu()
