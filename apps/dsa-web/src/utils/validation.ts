interface ValidationResult {
  valid: boolean;
  message?: string;
  normalized: string;
}

// 兼容台股/A股/港股/美股常見代碼格式的基礎校驗
export const validateStockCode = (value: string): ValidationResult => {
  const normalized = value.trim().toUpperCase();

  if (!normalized) {
    return { valid: false, message: '請輸入股票代碼', normalized };
  }

  const patterns = [
    /^\d{4}\.TW(O)?$/, // 台股 4 位數字 + .TW 或 .TWO
    /^\d{6}(\.(SS|SZ))?$/, // A 股 6 位數字（可帶 .SS/.SZ）
    /^(SH|SZ)\d{6}$/, // A 股帶交易所前綴
    /^\d{4,5}(\.HK)?$/, // 港股 4-5 位數字（可帶 .HK）
    /^[A-Z]{1,6}(\.[A-Z]{1,2})?$/, // 美股常見 Ticker
  ];

  const valid = patterns.some((regex) => regex.test(normalized));

  return {
    valid,
    message: valid ? undefined : '股票代碼格式不正確',
    normalized,
  };
};
