"""A compact CNN for wafer map classification.

Small on purpose: it trains on a laptop CPU in minutes on 64x64 maps and is
easy to explain in an interview. Swap in a ResNet later if you want to compare.
"""
from __future__ import annotations

import torch
from torch import nn


def _block(c_in: int, c_out: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(c_in, c_out, 3, padding=1, bias=False),
        nn.BatchNorm2d(c_out),
        nn.ReLU(inplace=True),
        nn.Conv2d(c_out, c_out, 3, padding=1, bias=False),
        nn.BatchNorm2d(c_out),
        nn.ReLU(inplace=True),
        nn.MaxPool2d(2),
    )


class WaferCNN(nn.Module):
    def __init__(self, n_classes: int = 9, in_channels: int = 2, width: int = 32, dropout: float = 0.3):
        super().__init__()
        self.features = nn.Sequential(
            _block(in_channels, width),
            _block(width, width * 2),
            _block(width * 2, width * 4),
        )
        self.head = nn.Sequential(
            nn.AdaptiveAvgPool2d(1),
            nn.Flatten(),
            nn.Dropout(dropout),
            nn.Linear(width * 4, n_classes),
        )

    @property
    def last_conv(self) -> nn.Module:
        """The layer Grad-CAM hooks into."""
        return self.features[-1][3]

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.features(x))
