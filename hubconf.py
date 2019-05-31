dependencies = ['torch', 'tqdm', 'boto3', 'requests', 'regex', 'ftfy', 'spacy']

from hubconfs.bert_hubconf import (
    bertTokenizer,
    bertModel,
    bertForNextSentencePrediction,
    bertForPreTraining,
    bertForMaskedLM,
    bertForSequenceClassification,
    bertForMultipleChoice,
    bertForQuestionAnswering,
    bertForTokenClassification
)
from hubconfs.gpt_hubconf import (
    openAIGPTTokenizer,
    openAIGPTModel,
    openAIGPTLMHeadModel,
    openAIGPTDoubleHeadsModel
)