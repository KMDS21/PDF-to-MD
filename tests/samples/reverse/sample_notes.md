---
title: "Sample Lecture Notes"
subject: "Reverse conversion test"
---

# Neural Networks — Week 3

**Lecture objectives:** understand backpropagation and vanishing gradients.

## 1. Recap

A neural network maps inputs to outputs through weighted layers (see [docs](https://example.com)).

- Training uses *gradient descent*
  - learning rate α controls step size
  - too large → divergence
- Loss: cross-entropy for classification

1. Forward pass
2. Compute loss
3. Backward pass

> Remember: matrix multiplication order matters.

## 2. Results table

| Layer | Neurons | Activation |
|---|---:|---|
| Input | 784 | — |
| Hidden | 256 | ReLU |
| Output | 10 | Softmax |

## 3. Code

```python
def forward(x, w):
    return x @ w
```

## 4. Summary

Key takeaway: *depth* helps only with proper initialization.

---

End of lecture notes.
