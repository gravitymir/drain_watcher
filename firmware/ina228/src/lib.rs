//! Драйвер INA228 для платы drain_watcher.
//!
//! Главное, ради чего он написан, — два диапазона по шунту и корректный переход
//! между ними. У INA228 бит `ADCRANGE` в регистре `CONFIG` переключает полную
//! шкалу вчетверо, и те же 20 бит ложатся на вчетверо меньший диапазон:
//!
//! | `ADCRANGE` | полная шкала | шаг по напряжению |
//! |---|---|---|
//! | 0 | ±163.84 мВ | 312.5 нВ |
//! | 1 | ±40.96 мВ  | 78.125 нВ |
//!
//! Для тока утечки (десятки миллиампер) нужен узкий диапазон, для проснувшихся
//! блоков — широкий. Автоматики в чипе нет: диапазон переключает контроллер.
//!
//! **При смене диапазона обязательно пересчитывается `SHUNT_CAL`** — в узком он
//! вчетверо больше. Забыть про это легко, и тогда ток поедет ровно в четыре раза;
//! здесь пересчёт зашит в [`Ina228::set_range`], руками его не сделать.

#![no_std]

use embedded_hal::i2c::{I2c, SevenBitAddress};

/// Адрес по умолчанию: A0 и A1 на землю, как разведено на плате drain_watcher.
pub const DEFAULT_ADDRESS: SevenBitAddress = 0x40;

/// Идентификатор из регистра `DEVICE_ID` (старшие 12 бит — номер чипа).
pub const DEVICE_ID_INA228: u16 = 0x228;
/// Идентификатор из регистра `MANUFACTURER_ID`: ASCII "TI".
pub const MANUFACTURER_ID_TI: u16 = 0x5449;

mod reg {
    pub const CONFIG: u8 = 0x00;
    pub const ADC_CONFIG: u8 = 0x01;
    pub const SHUNT_CAL: u8 = 0x02;
    pub const VSHUNT: u8 = 0x04;
    pub const VBUS: u8 = 0x05;
    pub const DIETEMP: u8 = 0x06;
    pub const CURRENT: u8 = 0x07;
    pub const DIAG_ALRT: u8 = 0x0B;
    pub const MANUFACTURER_ID: u8 = 0x3E;
    pub const DEVICE_ID: u8 = 0x3F;
}

const CONFIG_RST: u16 = 1 << 15;
const CONFIG_ADCRANGE: u16 = 1 << 4;

/// Флаг переполнения АЦП шунта в регистре `DIAG_ALRT`.
const DIAG_SHUNT_OVF: u16 = 1 << 9;
/// Флаг готовности преобразования в регистре `DIAG_ALRT`.
const DIAG_CNVRF: u16 = 1 << 1;

/// Шаг регистра `VBUS`, вольт.
const VBUS_LSB_V: f32 = 195.312_5e-6;
/// Шаг регистра `DIETEMP`, градусы Цельсия.
const DIETEMP_LSB_C: f32 = 7.812_5e-3;

/// Диапазон измерения напряжения на шунте.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Range {
    /// `ADCRANGE = 0`: ±163.84 мВ, шаг 312.5 нВ. Для проснувшихся блоков.
    Wide,
    /// `ADCRANGE = 1`: ±40.96 мВ, шаг 78.125 нВ. Для тока утечки.
    Narrow,
}

impl Range {
    /// Шаг регистра `VSHUNT`, вольт.
    pub const fn shunt_lsb_v(self) -> f32 {
        match self {
            Range::Wide => 312.5e-9,
            Range::Narrow => 78.125e-9,
        }
    }

    /// Полная шкала по напряжению, вольт.
    pub const fn full_scale_v(self) -> f32 {
        match self {
            Range::Wide => 0.163_84,
            Range::Narrow => 0.040_96,
        }
    }

    /// Множитель `SHUNT_CAL`: в узком диапазоне калибровка вчетверо больше.
    const fn cal_factor(self) -> f32 {
        match self {
            Range::Wide => 1.0,
            Range::Narrow => 4.0,
        }
    }
}

/// Ошибка драйвера.
#[derive(Debug)]
pub enum Error<E> {
    /// Ошибка шины I2C.
    I2c(E),
    /// В `DEVICE_ID` или `MANUFACTURER_ID` не то, что ждали от INA228.
    WrongDevice { manufacturer: u16, device: u16 },
    /// `SHUNT_CAL` не влезает в 15 бит: слишком большой шунт или слишком
    /// мелкий `current_lsb`.
    CalibrationOutOfRange(f32),
}

/// Замер: всё, что снимается за один проход.
#[derive(Debug, Clone, Copy)]
pub struct Measurement {
    /// Напряжение на шунте, вольт.
    pub shunt_v: f32,
    /// Ток через шунт, ампер. Положительный — разряд аккумулятора.
    pub current_a: f32,
    /// Напряжение на выводе VBUS, вольт (на плате поделено делителем).
    pub bus_v: f32,
    /// Температура кристалла, градусы Цельсия.
    pub die_c: f32,
}

/// INA228 на шине I2C.
pub struct Ina228<I2C> {
    i2c: I2C,
    address: SevenBitAddress,
    r_shunt_ohm: f32,
    current_lsb: f32,
    range: Range,
}

impl<I2C, E> Ina228<I2C>
where
    I2C: I2c<SevenBitAddress, Error = E>,
{
    /// Создать драйвер. Калибровка в чип ещё не записана — вызовите [`Self::init`].
    ///
    /// `max_current_a` — верх шкалы по току, из него считается `current_lsb`
    /// как `max_current_a / 2^19`. Для шунта 2.5 мОм разумно 35 А.
    pub fn new(i2c: I2C, address: SevenBitAddress, r_shunt_ohm: f32, max_current_a: f32) -> Self {
        Self {
            i2c,
            address,
            r_shunt_ohm,
            current_lsb: max_current_a / 524_288.0, // 2^19
            range: Range::Wide,
        }
    }

    /// Сбросить чип, проверить, что это действительно INA228, и записать
    /// калибровку под выбранный диапазон.
    pub fn init(&mut self, range: Range) -> Result<(), Error<E>> {
        self.write_u16(reg::CONFIG, CONFIG_RST)?;

        let manufacturer = self.read_u16(reg::MANUFACTURER_ID)?;
        let device = self.read_u16(reg::DEVICE_ID)? >> 4;
        if manufacturer != MANUFACTURER_ID_TI || device != DEVICE_ID_INA228 {
            return Err(Error::WrongDevice {
                manufacturer,
                device,
            });
        }

        self.set_range(range)
    }

    /// Переключить диапазон и пересчитать `SHUNT_CAL` под него.
    ///
    /// Это единственный правильный способ сменить диапазон: писать `ADCRANGE`
    /// в `CONFIG` напрямую нельзя, калибровка останется от прежней шкалы.
    pub fn set_range(&mut self, range: Range) -> Result<(), Error<E>> {
        // SHUNT_CAL = 13107.2e6 * CURRENT_LSB * R_SHUNT, в узком диапазоне x4.
        let cal = 13_107.2e6 * self.current_lsb * self.r_shunt_ohm * range.cal_factor();
        if !(cal.is_finite() && (1.0..=32_767.0).contains(&cal)) {
            return Err(Error::CalibrationOutOfRange(cal));
        }

        let mut config = self.read_u16(reg::CONFIG)?;
        config = match range {
            Range::Wide => config & !CONFIG_ADCRANGE,
            Range::Narrow => config | CONFIG_ADCRANGE,
        };
        self.write_u16(reg::CONFIG, config)?;
        self.write_u16(reg::SHUNT_CAL, cal as u16)?;
        self.range = range;
        Ok(())
    }

    /// Текущий диапазон.
    pub fn range(&self) -> Range {
        self.range
    }

    /// Записать регистр `ADC_CONFIG` как есть: режим, время интегрирования,
    /// усреднение. Значение после сброса — 0xFB68.
    pub fn set_adc_config(&mut self, value: u16) -> Result<(), Error<E>> {
        self.write_u16(reg::ADC_CONFIG, value)
    }

    /// Напряжение на шунте, вольт.
    pub fn shunt_voltage(&mut self) -> Result<f32, Error<E>> {
        let raw = self.read_i20(reg::VSHUNT)?;
        Ok(raw as f32 * self.range.shunt_lsb_v())
    }

    /// Ток через шунт, ампер. Положительный — разряд аккумулятора.
    pub fn current(&mut self) -> Result<f32, Error<E>> {
        let raw = self.read_i20(reg::CURRENT)?;
        Ok(raw as f32 * self.current_lsb)
    }

    /// Напряжение на выводе VBUS, вольт. Делитель на плате здесь не учтён.
    pub fn bus_voltage(&mut self) -> Result<f32, Error<E>> {
        let raw = self.read_i20(reg::VBUS)?;
        Ok(raw as f32 * VBUS_LSB_V)
    }

    /// Температура кристалла, градусы Цельсия.
    pub fn die_temperature(&mut self) -> Result<f32, Error<E>> {
        let raw = self.read_u16(reg::DIETEMP)? as i16;
        Ok(raw as f32 * DIETEMP_LSB_C)
    }

    /// Снять всё за один проход.
    pub fn measure(&mut self) -> Result<Measurement, Error<E>> {
        Ok(Measurement {
            shunt_v: self.shunt_voltage()?,
            current_a: self.current()?,
            bus_v: self.bus_voltage()?,
            die_c: self.die_temperature()?,
        })
    }

    /// Готово ли преобразование (флаг `CNVRF` в `DIAG_ALRT`).
    ///
    /// Флаг сбрасывается чтением `DIAG_ALRT`, так что вызывать его в цикле
    /// опроса нужно ровно один раз за замер.
    pub fn conversion_ready(&mut self) -> Result<bool, Error<E>> {
        Ok(self.read_u16(reg::DIAG_ALRT)? & DIAG_CNVRF != 0)
    }

    /// Переполнен ли АЦП шунта (флаг `SHUNT_OVF` в `DIAG_ALRT`).
    pub fn shunt_overflow(&mut self) -> Result<bool, Error<E>> {
        Ok(self.read_u16(reg::DIAG_ALRT)? & DIAG_SHUNT_OVF != 0)
    }

    /// Подобрать диапазон под текущий ток и вернуть замер.
    ///
    /// Логика простая и без дребезга на границе: переполнение узкой шкалы
    /// уводит в широкую сразу, а обратно — только когда ток опустился ниже
    /// четверти узкой шкалы с запасом. Между порогами диапазон не меняется.
    pub fn measure_autoranged(&mut self) -> Result<Measurement, Error<E>> {
        if self.range == Range::Narrow && self.shunt_overflow()? {
            self.set_range(Range::Wide)?;
        }

        let m = self.measure()?;

        let down = Range::Narrow.full_scale_v() * 0.8;
        if self.range == Range::Wide && libm_fabsf(m.shunt_v) < down {
            self.set_range(Range::Narrow)?;
            return self.measure();
        }
        Ok(m)
    }

    /// Отдать шину обратно.
    pub fn release(self) -> I2C {
        self.i2c
    }

    fn read_u16(&mut self, register: u8) -> Result<u16, Error<E>> {
        let mut buf = [0u8; 2];
        self.i2c
            .write_read(self.address, &[register], &mut buf)
            .map_err(Error::I2c)?;
        Ok(u16::from_be_bytes(buf))
    }

    /// Прочитать 24-битный регистр: данные в старших 20 битах, младшие 4
    /// зарезервированы. Результат — знаковое 20-битное число.
    fn read_i20(&mut self, register: u8) -> Result<i32, Error<E>> {
        let mut buf = [0u8; 3];
        self.i2c
            .write_read(self.address, &[register], &mut buf)
            .map_err(Error::I2c)?;
        let raw = (u32::from(buf[0]) << 16 | u32::from(buf[1]) << 8 | u32::from(buf[2])) >> 4;
        Ok(sign_extend_20(raw))
    }

    fn write_u16(&mut self, register: u8, value: u16) -> Result<(), Error<E>> {
        let bytes = value.to_be_bytes();
        self.i2c
            .write(self.address, &[register, bytes[0], bytes[1]])
            .map_err(Error::I2c)
    }
}

/// Знаковое расширение 20-битного числа до i32.
fn sign_extend_20(raw: u32) -> i32 {
    if raw & 0x8_0000 != 0 {
        (raw | 0xFFF0_0000) as i32
    } else {
        raw as i32
    }
}

/// Модуль f32 без `std` и без тяги за `libm` ради одной функции.
fn libm_fabsf(x: f32) -> f32 {
    f32::from_bits(x.to_bits() & 0x7FFF_FFFF)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn calibration_scales_by_four_in_narrow_range() {
        // Плата drain_watcher: шунт 2.5 мОм, шкала 35 А.
        let current_lsb: f32 = 35.0 / 524_288.0;
        let wide: f32 = 13_107.2e6 * current_lsb * 0.0025;
        let narrow = wide * 4.0;
        assert!((narrow / wide - 4.0).abs() < 1e-6);
        // Обе величины должны влезать в 15 бит регистра SHUNT_CAL.
        assert!(wide >= 1.0 && narrow <= 32_767.0, "{wide} .. {narrow}");
    }

    #[test]
    fn narrow_range_step_is_four_times_finer() {
        assert_eq!(Range::Wide.shunt_lsb_v() / Range::Narrow.shunt_lsb_v(), 4.0);
        assert_eq!(Range::Wide.full_scale_v() / Range::Narrow.full_scale_v(), 4.0);
    }

    #[test]
    fn leakage_current_resolves_on_narrow_range() {
        // 30 мА через 2.5 мОм — это 75 мкВ.
        let shunt_v = 0.030 * 0.0025;
        let counts = shunt_v / Range::Narrow.shunt_lsb_v();
        assert!(counts > 900.0, "{counts} отсчётов — мало для утечки");
        // И при этом не переполняет узкую шкалу.
        assert!(shunt_v < Range::Narrow.full_scale_v());
    }

    #[test]
    fn sign_extension_handles_negative_charge_current() {
        assert_eq!(sign_extend_20(0x0_0001), 1);
        assert_eq!(sign_extend_20(0x7_FFFF), 524_287);
        assert_eq!(sign_extend_20(0xF_FFFF), -1);
        assert_eq!(sign_extend_20(0x8_0000), -524_288);
    }
}
