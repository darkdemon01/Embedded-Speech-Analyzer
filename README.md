# Real-Time Digital Storage Oscilloscope (DSO) for Speech Signal Analysis

## Overview
This repository contains a complete end-to-end Digital Signal Processing (DSP) system designed for high-fidelity speech signal analysis and multi-domain visualization[cite: 5]. The architecture utilizes a hardware-software co-design philosophy, dividing tasks between an ESP32 microcontroller and a Raspberry Pi 4B to optimize performance and real-time responsiveness[cite: 5].

## Repository Structure
* `esp32_dso_firmware.ino`: The C/C++ firmware for the ESP32 that handles periodic sampling, scaling to 16-bit PCM format, DC offset removal, and I2S transmission[cite: 6, 7].
* `pi_dso_app.py`: The Python application for the Raspberry Pi that receives the I2S audio stream, performs DSP operations, and renders the PyQt5 graphical user interface[cite: 6, 8].

## Hardware Architecture
* **Analog Front-End:** A biasing circuit shifts the microphone signal to a 1.65V DC midpoint to prevent clipping[cite: 5]. It utilizes a 10kΩ voltage divider, a 1µF AC coupling capacitor to block DC offset, and a 100nF capacitor to filter high-frequency power supply noise[cite: 5].
* **Signal Acquisition (ESP32):** Configures GPIO34 for high-speed 12-bit ADC sampling at 16,000 Hz[cite: 5, 7]. It implements a real-time DC-block IIR filter to remove the bias offset and ensure a zero-centered AC signal is passed forward[cite: 5, 7].
* **Digital Link (I2S):** The ESP32 streams continuous digital audio buffers to the Raspberry Pi via the I2S protocol using GPIO pins 22 (BCLK), 25 (LRCK), and 26 (DOUT)[cite: 5, 7].

## DSP Pipeline & Features
The Raspberry Pi processes the incoming audio stream to extract and visualize the following real-time metrics:
* **Time Domain Analysis:** Extracts 50ms sample windows to visualize raw waveform structures and transient details[cite: 5, 8].
* **Frequency Domain (FFT):** Computes a 2048-point Fast Fourier Transform (FFT) with a Hanning window, converted to decibels, to analyze the 300-3400 Hz speech band[cite: 5, 8].
* **Temporal Evolution:** Generates a rolling spectrogram to display a time-frequency heatmap of vowel formants and pitch transitions[cite: 5].
* **Signal Quality & Pitch:** Calculates Root Mean Square (RMS) power, Peak level amplitude, Total Harmonic Distortion (THD) ratio, and the Fundamental Frequency (F0)[cite: 5, 6].
* **Note Detection:** Translates the detected fundamental frequency into standard musical notation (e.g., C4, A#3)[cite: 5].

