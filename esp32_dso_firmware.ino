/*
 * ESP32 DSO Firmware
 * ==================
 * - Samples analog mic signal on GPIO34 (ADC1_CH6)
 * - Mic bias circuit: 3.3V → 10kΩ R1 → node → 10kΩ R2 → GND
 *   with 1µF coupling cap from mic sleeve, 100nF bypass cap
 * - Transmits 16-bit PCM audio via I2S to Raspberry Pi
 * 
 * I2S Pins (Master):
 *   BCLK  → GPIO22  → Pi GPIO18 (Pin 12)
 *   LRCK  → GPIO25  → Pi GPIO19 (Pin 35)
 *   DOUT  → GPIO26  → Pi GPIO20 (Pin 38)
 *   GND   → GND     → Pi GND   (Pin 6)
 * 
 * Sample Rate: 16000 Hz (ideal for speech)
 * Bit Depth  : 16-bit
 */

#include <driver/i2s.h>
#include <driver/adc.h>
#include "esp_adc_cal.h"

// ── Configuration ──────────────────────────────────────────────────────────
#define SAMPLE_RATE       16000
#define ADC_CHANNEL       ADC1_CHANNEL_6   // GPIO34
#define ADC_ATTEN         ADC_ATTEN_DB_11  // 0–3.9V range
#define ADC_WIDTH         ADC_WIDTH_BIT_12 // 12-bit = 0–4095
#define DC_BIAS           2048             // ~1.65V midpoint after bias circuit
#define I2S_NUM           I2S_NUM_0
#define I2S_BCLK_PIN      22
#define I2S_LRCK_PIN      25
#define I2S_DOUT_PIN      26
#define DMA_BUF_COUNT     8
#define DMA_BUF_LEN       256             // samples per DMA buffer
// ───────────────────────────────────────────────────────────────────────────

static esp_adc_cal_characteristics_t adc_chars;

// ── I2S Initialisation ─────────────────────────────────────────────────────
void i2s_init() {
  i2s_config_t cfg = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate          = SAMPLE_RATE,
    .bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,  // mono
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = DMA_BUF_COUNT,
    .dma_buf_len          = DMA_BUF_LEN,
    .use_apll             = true,          // use APLL for accurate clock
    .tx_desc_auto_clear   = true
  };

  i2s_pin_config_t pins = {
    .bck_io_num   = I2S_BCLK_PIN,
    .ws_io_num    = I2S_LRCK_PIN,
    .data_out_num = I2S_DOUT_PIN,
    .data_in_num  = I2S_PIN_NO_CHANGE
  };

  ESP_ERROR_CHECK(i2s_driver_install(I2S_NUM, &cfg, 0, NULL));
  ESP_ERROR_CHECK(i2s_set_pin(I2S_NUM, &pins));
  ESP_ERROR_CHECK(i2s_set_clk(I2S_NUM, SAMPLE_RATE, I2S_BITS_PER_SAMPLE_16BIT, I2S_CHANNEL_MONO));
  Serial.println("[I2S] Initialised OK");
}

// ── ADC Initialisation ─────────────────────────────────────────────────────
void adc_init() {
  adc1_config_width(ADC_WIDTH);
  adc1_config_channel_atten(ADC_CHANNEL, ADC_ATTEN);
  esp_adc_cal_characterize(ADC_UNIT_1, ADC_ATTEN, ADC_WIDTH, 1100, &adc_chars);
  Serial.println("[ADC] Initialised OK  (GPIO34, 0–3.9V, 12-bit)");
}

// ── Helpers ────────────────────────────────────────────────────────────────

// Simple DC-block IIR filter (removes residual bias drift)
// y[n] = x[n] - x[n-1] + 0.995 * y[n-1]
static int32_t dcblock_x_prev = 0;
static float   dcblock_y_prev = 0.0f;

inline int16_t dc_block(int32_t raw) {
  float y = (float)(raw - DC_BIAS)
            - (float)dcblock_x_prev
            + 0.995f * dcblock_y_prev;
  dcblock_x_prev = raw - DC_BIAS;
  dcblock_y_prev = y;
  // scale 12-bit centred value → 16-bit
  int32_t out = (int32_t)(y * 16);
  if (out >  32767) out =  32767;
  if (out < -32768) out = -32768;
  return (int16_t)out;
}

// ── Sample buffer ──────────────────────────────────────────────────────────
#define WRITE_BUF_SAMPLES  DMA_BUF_LEN
static int16_t write_buf[WRITE_BUF_SAMPLES];

// ── Timing ─────────────────────────────────────────────────────────────────
// We want exactly SAMPLE_RATE samples/sec.
// Each sample should take 1,000,000 / SAMPLE_RATE µs.
#define SAMPLE_PERIOD_US  (1000000UL / SAMPLE_RATE)   // 62 µs @ 16kHz

// ── Arduino entry points ───────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n=== ESP32 Speech DSO Firmware ===");
  Serial.printf("Sample rate : %d Hz\n", SAMPLE_RATE);
  Serial.printf("DMA buffers : %d × %d samples\n", DMA_BUF_COUNT, DMA_BUF_LEN);

  adc_init();
  i2s_init();
  Serial.println("[READY] Streaming audio via I2S …");
}

void loop() {
  static uint32_t t_last = 0;
  static int      idx    = 0;

  uint32_t now = micros();
  if ((now - t_last) >= SAMPLE_PERIOD_US) {
    t_last = now;

    // Read ADC and apply DC-block filter
    int32_t raw = adc1_get_raw(ADC_CHANNEL);
    write_buf[idx++] = dc_block(raw);

    // When buffer is full, write to I2S DMA
    if (idx >= WRITE_BUF_SAMPLES) {
      idx = 0;
      size_t bytes_written = 0;
      i2s_write(I2S_NUM,
                write_buf,
                WRITE_BUF_SAMPLES * sizeof(int16_t),
                &bytes_written,
                portMAX_DELAY);
    }
  }
}
