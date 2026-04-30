"""Reusable PWM heat pad driver."""

from machine import PWM, Pin


class HeatPad:
    """Controls a single heat pad duty cycle in percent."""

    def __init__(self, pin, frequency_hz=1000):
        self._pwm = PWM(Pin(pin))
        self._pwm.freq(frequency_hz)
        self._duty_pct = 0
        self.set_duty_pct(0)

    def set_duty_pct(self, duty_pct):
        duty = int(duty_pct)
        if duty < 0 or duty > 100:
            raise ValueError("duty out of range")
        self._duty_pct = duty
        self._pwm.duty_u16((duty * 65535) // 100)
        return self._duty_pct

    def get_duty_pct(self):
        return self._duty_pct
